"""
Nexus Agent Adapter for Musique
"""

import sys
import os

# Add local path and root path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from musique_utils import get_musique_env, llm
from experiment_utils import EnvWrapper
from wrappers import f1_score
from src.agents.nexus.nexus_agent import NexusAgent

def run_nexus(idx, prompt_template=None, to_print=True):
    """
    Run Nexus agent on Musique.
    """
    if to_print:
        print("="*60)
        print("[FRAMEWORK] Musique Nexus")
        print("="*60)

    # Setup 
    env = get_musique_env()
    wrapped_env = EnvWrapper(env)
    
    question_text = wrapped_env.reset(idx)
    
    # Initialize Nexus
    # We use task_type="musique" to trigger correct adjudicator implementation if added
    # Or fallback to QA default
    agent = NexusAgent(llm_func=llm, env=wrapped_env, task_type="musique")
    
    answer, debug_info = agent.solve(question_text)
    
    # Cleanup answer
    if answer:
        answer = answer.replace("Answer:", "").strip()
    
    # Finalize in environment to get exact reward
    final_action = f"finish[{answer}]"
    obs, reward, done, info = wrapped_env.step(final_action)
    
    # Compute F1
    gt_str = info.get('gt_answer', '') or ''
    answer_str = answer or ''
    f1_val = f1_score(answer_str, gt_str)[0] if answer_str and gt_str else 0.0

    info_dict = {
        'question_idx': idx,
        'question_text': info.get('question'),
        'answer': answer,
        'gt_answer': info.get('gt_answer'),
        'em': reward,
        'f1': f1_val,
        'reward': reward,
        'n_calls': agent.n_calls,
        'n_badcalls': 0,
        'steps': info.get('steps'),
        'decomposition': info.get('decomposition'),
        'traj': debug_info.get('traj', ''),
        'framework': 'nexus'
    }
    
    if to_print:
        print(f"[RESULT] Answer: {answer} | GT: {info_dict['gt_answer']} | EM: {reward}")
        
    return reward, info_dict

if __name__ == '__main__':
    run_nexus(0)
