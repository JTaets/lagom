import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

import gym.spaces as spaces
import lagom
import lagom.utils as utils
import lagom.rl as rl


class Actor(lagom.nn.Module):
    def __init__(self, config, env, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.env = env
        
        self.feature_layers = lagom.nn.make_fc(spaces.flatdim(env.observation_space), [400, 300])
        self.action_head = nn.Linear(300, spaces.flatdim(env.action_space))
        
        # TODO: use Rescale wrappers in gym instead
        assert np.unique(env.action_space.high).size == 1
        assert -np.unique(env.action_space.low).item() == np.unique(env.action_space.high).item()
        self.max_action = env.action_space.high[0]
        
    def forward(self, x):
        for layer in self.feature_layers:
            x = F.relu(layer(x))
        x = self.max_action*torch.tanh(self.action_head(x))
        return x


class Critic(lagom.nn.Module):
    def __init__(self, config, env, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.env = env
        
        obs_dim = spaces.flatdim(env.observation_space)
        action_dim = spaces.flatdim(env.action_space)
        # Q1
        self.first_feature_layers = lagom.nn.make_fc(obs_dim + action_dim, [400, 300])
        self.first_Q_head = nn.Linear(300, 1)
        # Q2
        self.second_feature_layers = lagom.nn.make_fc(obs_dim + action_dim, [400, 300])
        self.second_Q_head = nn.Linear(300, 1)
        
    def Q1(self, x, action):
        x = torch.cat([x, action], dim=-1)
        for layer in self.first_feature_layers:
            x = F.relu(layer(x))
        x = self.first_Q_head(x)
        return x
    
    def Q2(self, x, action):
        x = torch.cat([x, action], dim=-1)
        for layer in self.second_feature_layers:
            x = F.relu(layer(x))
        x = self.second_Q_head(x)
        return x
        
    def forward(self, x, action):
        return self.Q1(x, action), self.Q2(x, action)
    
    
class Agent(lagom.BaseAgent):
    def __init__(self, config, env, **kwargs):
        super().__init__(config, env, **kwargs)
        
        self.actor = Actor(config, env, **kwargs)
        self.actor_target = Actor(config, env, **kwargs)
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=config['agent.actor.lr'])
        
        self.critic = Critic(config, env, **kwargs)
        self.critic_target = Critic(config, env, **kwargs)
        self.critic_target.load_state_dict(self.critic.state_dict())
        self.critic_optimizer = optim.Adam(self.critic.parameters(), lr=config['agent.critic.lr'])
        
        self.register_buffer('total_timestep', torch.tensor(0))
        # TODO: remove it after using Rescale wrapper on action space
        self.max_action = env.action_space.high[0]
        
    def polyak_update_target(self):
        p = self.config['agent.polyak']
        for param, target_param in zip(self.actor.parameters(), self.actor_target.parameters()):
            target_param.data.copy_(p*target_param.data + (1 - p)*param.data)
        for param, target_param in zip(self.critic.parameters(), self.critic_target.parameters()):
            target_param.data.copy_(p*target_param.data + (1 - p)*param.data)

    def choose_action(self, x, **kwargs):
        obs = torch.as_tensor(x.observation).float().to(self.config.device).unsqueeze(0)
        with torch.no_grad():
            action = utils.numpify(self.actor(obs).squeeze(0), 'float')
        if kwargs['mode'] == 'train':
            eps = np.random.normal(0.0, self.config['agent.action_noise'], size=action.shape)
            action = np.clip(action + eps, self.env.action_space.low, self.env.action_space.high)
        out = {}
        out['raw_action'] = action
        return out

    def learn(self, D, **kwargs):
        replay = kwargs['replay']
        T = kwargs['T']
        list_actor_loss, list_critic_loss, Q1_vals, Q2_vals = [], [], [], []
        for i in range(T):
            samples = replay.sample(self.config['replay.batch_size'])
            observations, actions, next_observations, rewards, masks = map(lambda x: torch.as_tensor(x).to(self.config.device), samples)
            
            Qs1, Qs2 = self.critic(observations, actions)
            with torch.no_grad():
                next_actions = self.actor_target(next_observations)
                eps = torch.empty_like(next_actions).normal_(0.0, self.config['agent.target_noise'])
                eps = eps.clamp(-self.config['agent.target_noise_clip'], self.config['agent.target_noise_clip'])
                next_actions = torch.clamp(next_actions + eps, -self.max_action, self.max_action)
                next_Qs1, next_Qs2 = self.critic_target(next_observations, next_actions)
                next_Qs = torch.min(next_Qs1, next_Qs2)
                targets = rewards + self.config['agent.gamma']*masks*next_Qs
            critic_loss = F.mse_loss(Qs1, targets.detach()) + F.mse_loss(Qs2, targets.detach())
            self.actor_optimizer.zero_grad()
            self.critic_optimizer.zero_grad()
            critic_loss.backward()
            critic_grad_norm = nn.utils.clip_grad_norm_(self.critic.parameters(), self.config['agent.max_grad_norm'])
            self.critic_optimizer.step()
            
            if i % self.config['agent.policy_delay'] == 0:
                actor_loss = -self.critic.Q1(observations, self.actor(observations)).mean()
                self.actor_optimizer.zero_grad()
                self.critic_optimizer.zero_grad()
                actor_loss.backward()
                actor_grad_norm = nn.utils.clip_grad_norm_(self.actor.parameters(), self.config['agent.max_grad_norm'])
                self.actor_optimizer.step()
                
                self.polyak_update_target()
                list_actor_loss.append(actor_loss)
            list_critic_loss.append(critic_loss)
            Q1_vals.append(Qs1)
            Q2_vals.append(Qs2)
        self.total_timestep += T
        
        out = {}
        out['actor_loss'] = torch.as_tensor(list_actor_loss).mean(0).item()
        out['actor_grad_norm'] = actor_grad_norm
        out['critic_loss'] = torch.as_tensor(list_critic_loss).mean(0).item()
        out['critic_grad_norm'] = critic_grad_norm
        describe_it = lambda x: describe(numpify(torch.cat(x), 'float').squeeze(), axis=-1, repr_indent=1, repr_prefix='\n')
        out['Q1'] = utils.describe(torch.cat(Q1_vals).squeeze(), axis=-1, repr_indent=1, repr_prefix='\n')
        out['Q2'] = utils.describe(torch.cat(Q2_vals).squeeze(), axis=-1, repr_indent=1, repr_prefix='\n')
        return out
    
    def checkpoint(self, logdir, num_iter):
        self.save(logdir/f'agent_{num_iter}.pth')
