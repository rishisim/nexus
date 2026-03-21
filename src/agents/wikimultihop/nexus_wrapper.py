"""
Nexus Wrapper for 2WikiMultiHop

This module provides a wrapper to run the Nexus agent on 2WikiMultiHop tasks.
"""

import sys
import os

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from wikimultihop_utils import WikiMultiHopEnv, llm, llm_judge_answer
from src.agents.nexus.nexus_agent import NexusAgent


def run_nexus(env: WikiMultiHopEnv, idx: int, to_print: bool = True):
    """
    Run Nexus agent on a single 2WikiMultiHop question.
    
    Args:
        env: The WikiMultiHop environment
        idx: Question index
        to_print: Whether to print progress
        
    Returns:
        Tuple of (reward, info_dict)
    """
    if to_print:
        print("=" * 60)
        print("[FRAMEWORK] Nexus (Scout -> Architect -> Adjudicator)")
        print("=" * 60)
    
    # Reset environment for this question
    question = env.reset(idx=idx)
    item = env.get_item(idx)
    
    if to_print:
        print(f"[IDX] {idx}")
        print(f"[TYPE] {item['type']}")
        print(f"[Q] {question}")
    
    # Initialize Nexus Agent
    agent = NexusAgent(llm_func=llm, env=env, task_type="hotpotqa")
    
    # Solve
    try:
        answer, debug_info = agent.solve(question)
    except Exception as e:
        import traceback
        traceback.print_exc()
        answer = "null"
        debug_info = {"traj": f"Error: {e}", "dossier": ""}
    
    # Finish action to get evaluation
    final_action = f"finish[{answer}]"
    if to_print:
        print(f"\n[FINAL ACTION] {final_action}")
    
    obs, reward, done, info = env.step(final_action)
    
    # LLM Judge evaluation
    gt_answer = info.get('gt_answer', 'UNKNOWN')
    llm_eval = llm_judge_answer(question, answer, gt_answer)
    
    # Construct result dict
    info_dict = {
        'question_idx': idx,
        'question_id': item['id'],
        'question_text': question,
        'question_type': item['type'],
        'answer': answer,
        'gt_answer': gt_answer,
        'em': info.get('em', 0.0),
        'f1': info.get('f1', 0.0),
        'reward': reward,
        'n_calls': agent.n_calls,
        'traj': debug_info.get('traj', ''),
        'dossier': debug_info.get('dossier', ''),
        'framework': 'nexus',
        'llm_correct': llm_eval['llm_correct'],
        'llm_explanation': llm_eval['llm_explanation']
    }
    
    if to_print:
        print(f"\n[RESULT] Answer: {answer}")
        print(f"[GT] {gt_answer}")
        print(f"[EM] {info_dict['em']} | [F1] {info_dict['f1']:.3f} | [LLM] {info_dict['llm_correct']}")
        print("=" * 60)
    
    return reward, info_dict
