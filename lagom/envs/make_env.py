import gym
from gym.wrappers import Monitor

from lagom.utils import Seeder
from .wrappers import GymWrapper

from functools import partial  # argument-free functions


def make_gym_env(env_id, seed, monitor=False, monitor_dir=None):
    r"""Create an OpenAI Gym environment, and wrap it into lagom-compatible :class:`Env`. 
    
    Example::
    
        >>> env = make_gym_env(env_id='CartPole-v1', seed=1, monitor=False)
        >>> env
        <GymWrapper, <TimeLimit<CartPoleEnv<CartPole-v1>>>>
        
        >>> env.reset()
        array([ 0.03073904,  0.00145001, -0.03088818, -0.03131252])
    
    Args:
        env_id (str): OpenAI Gym environment ID, e.g. 'Pendulum-v0', 'Ant-v2'
        seed (int): random seed for the environment
        monitor (bool, optional): If ``True``, then wrap the enviroment with Monitor for video recording.  
        monitor_dir (str, optional): directory to save all data from Monitor. 
        
    Returns
    -------
    env : Env
        lagom-compatible environment
    """
    env = gym.make(env_id)
    if monitor:
        env = Monitor(env, monitor_dir)
    env = GymWrapper(env)
    env.seed(seed)
    
    return env
    

def make_envs(make_env, env_id, num_env, init_seed, **kwargs):
    r"""Create a list of argument-free make_env() functions based on the given settings. 
    
    .. note::
    
        Each make_env function in the list uses different random seeds generated by :class:`Seeder`. 
    
    Example::
        
        >>> make_envs(make_env=make_gym_env, env_id='CartPole-v1', num_env=3, init_seed=0)
        [functools.partial(<function make_gym_env at 0x7f2127b5ce18>, env_id='CartPole-v1', seed=209652396),
         functools.partial(<function make_gym_env at 0x7f2127b5ce18>, env_id='CartPole-v1', seed=398764591),
         functools.partial(<function make_gym_env at 0x7f2127b5ce18>, env_id='CartPole-v1', seed=924231285)]
    
    Args:
        make_env (function): a function to create an environment
        env_id (str): environment ID, e.g. 'Pendulum-v0', 'Ant-v2'
        num_env (int): number of environments to create. 
        init_seed (int): initial seed for :class:`Seeder` to sample random seeds. 
        **kwargs: keyword aguments used to specify other options for make_env. 
        
    Returns
    -------
    list_make_env : list
        a list of argument-free make_env() functions, each associated with different random seed. 
    """
    # Generate different seeds for each environment
    seeder = Seeder(init_seed=init_seed)
    seeds = seeder(size=num_env)
    
    # Use partial to generate a list of argument-free make_env, each with different seed
    list_make_env = [partial(make_env, env_id=env_id, seed=seed, **kwargs) for seed in seeds]
    
    return list_make_env


def make_vec_env(vec_env_class, make_env, env_id, num_env, init_seed, **kwargs):
    r"""Create a vectorized environment (i.e. :class:`VecEnv`). 
    
    Example::
    
        >>> from lagom.envs.vec_env import SerialVecEnv
        >>> make_vec_env(vec_env_class=SerialVecEnv, make_env=make_gym_env, env_id='CartPole-v1', num_env=5, init_seed=1)
        <SerialVecEnv: CartPole-v1, n: 5>
    
    Args:
        vec_env_class (VecEnv): vectorized environment class e.g. :class:`SerialVecEnv`, :class:`ParallelVecEnv`
        make_env (function): a function to create an environment
        env_id (str): environment ID, e.g. 'Pendulum-v0', 'Ant-v2'
        num_env (int): number of environments to create. 
        init_seed (int): initial seed for :class:`Seeder` to sample random seeds. 
        **kwargs: keyword aguments used to specify other options. 
        
    Returns
    -------
    venv : VecEnv
        created vectorized environment
    """
    list_make_env = make_envs(make_env=make_env, 
                              env_id=env_id, 
                              num_env=num_env, 
                              init_seed=init_seed, 
                              **kwargs)
    
    venv = vec_env_class(list_make_env=list_make_env)
    
    return venv
