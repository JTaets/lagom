import torch
import numpy as np

from lagom.envs import EnvSpec

from lagom.history import BatchEpisode

from lagom.runner import BaseRunner


class EpisodeRunner(BaseRunner):
    def __init__(self, config, agent, env):
        super().__init__(config, agent, env)
        
        self.env_spec = EnvSpec(self.env)
        
    def __call__(self, T):
        D = BatchEpisode(self.env_spec)
        
        obs = self.env.reset()
        D.add_observation(obs)
        # reset agent: e.g. RNN states because initial observation
        self.agent.reset(self.config)
        
        for t in range(T):
            info = {}
            out_agent = self.agent.choose_action(obs, info=info)
            
            action = out_agent.pop('action')
            if torch.is_tensor(action):
                raw_action = list(action.detach().cpu().numpy())
            else:
                raw_action = action
            D.add_action(raw_action)
            
            obs, reward, done, info = self.env.step(raw_action)
            D.add_observation(obs)
            D.add_reward(reward)
            D.add_done(done)
            D.add_info(info)
            [D.set_completed(n) for n, d in enumerate(done) if d]
            
            # Record other information: e.g. log-probability of action, policy entropy
            D.add_batch_info(out_agent)
            
            if all(D.completes):
                break
                
        return D