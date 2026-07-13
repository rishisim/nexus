import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from creak_utils import get_creak_env, llm
from experiment_utils import EnvWrapper

from src.agents.nexus.nexus_agent import NexusAgent


def run_nexus(idx, prompt_template=None, to_print=True):
    """Run Nexus agent on a single CREAK claim."""
    if to_print:
        print("="*60)
        print("[FRAMEWORK] Nexus (Scout -> Architect -> Adjudicator)")
        print("="*60)

    env = get_creak_env()
    wrapped_env = EnvWrapper(env)

    question = wrapped_env.reset(idx=idx)

    if to_print:
        print(f"[EX] Index: {idx}")
        print(f"[Q] {question}")

    agent = NexusAgent(llm_func=llm, env=wrapped_env, task_type="creak")

    try:
        answer, debug_info = agent.solve(question)
    except Exception as e:
        import traceback
        traceback.print_exc()
        answer = "FALSE"
        debug_info = {"traj": f"Error: {e}", "dossier": ""}

    final_action = f"finish[{answer}]"
    if to_print:
        print(f"[FINAL ACTION] {final_action}")

    obs, reward, done, info = wrapped_env.step(final_action)

    gt_answer = info.get('gt_answer', 'UNKNOWN')

    info_dict = {
        'question_idx': idx,
        'question_text': question,
        'answer': answer,
        'gt_answer': gt_answer,
        'em': info.get('em', 0.0),
        'f1': info.get('f1', 0.0),
        'reward': reward,
        'n_calls': agent.n_calls,
        'n_badcalls': 0,
        'traj': debug_info.get('traj', ''),
        'framework': 'nexus',
    }

    if to_print:
        print(f"[RESULT] Answer: {answer} | GT: {gt_answer} | EM: {info_dict['em']}")
        print("="*60)

    return reward, info_dict
