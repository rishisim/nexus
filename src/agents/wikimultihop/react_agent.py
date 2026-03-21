"""
ReAct Agent for 2WikiMultiHop

Standard single-trace ReAct agent for the 2WikiMultiHop multi-hop QA dataset.
"""

import sys
import os

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from wikimultihop_utils import WikiMultiHopEnv, llm, llm_judge_answer


# Prompt template for ReAct
REACT_PROMPT = """Solve a question answering task with interleaving Thought, Action, Observation steps. Thought can reason about the current situation, and Action can be three types: 
(1) Search[entity], which searches the exact entity on Wikipedia and returns the first paragraph if it exists. If not, it will return some similar entities to search.
(2) Lookup[keyword], which returns the next sentence containing keyword in the current passage.
(3) Finish[answer], which returns the answer and finishes the task.
If the question is based on a false premise or the information needed to answer is not available, answer "null".

Question: """


def run_react(env: WikiMultiHopEnv, idx: int, to_print: bool = True):
    """
    Run standard ReAct agent on a single 2WikiMultiHop question.
    
    Args:
        env: The WikiMultiHop environment
        idx: Question index
        to_print: Whether to print progress
        
    Returns:
        Tuple of (reward, info_dict)
    """
    if to_print:
        print("=" * 60)
        print("[FRAMEWORK] Standard ReAct (Single Trace)")
        print("=" * 60)
    
    # Reset environment for this question
    question = env.reset(idx=idx)
    item = env.get_item(idx)
    
    if to_print:
        print(f"[IDX] {idx}")
        print(f"[TYPE] {item['type']}")
        print(f"[Q] {question}")
    
    # Initialize prompt
    current_prompt = REACT_PROMPT + question + "\n"
    
    n_calls, n_badcalls = 0, 0
    trajectory_steps = []
    done = False
    info = {}
    reward = 0.0
    answer = "null"
    
    # Run ReAct loop (max 7 steps)
    for i in range(1, 8):
        n_calls += 1
        
        # Generate thought and action
        thought_action = llm(
            current_prompt + f"Thought {i}:", 
            stop=[f"\nObservation {i}:"],
            temperature=0.0
        )
        
        # Parse thought and action
        try:
            thought, action = thought_action.strip().split(f"\nAction {i}: ")
        except:
            if to_print:
                print(f"[ERROR] Parsing thought/action: '{thought_action}'")
            n_badcalls += 1
            thought = thought_action.strip().split('\n')[0] if thought_action else "Error in thought generation"
            action_prompt = current_prompt + f"Thought {i}: {thought}\nAction {i}:"
            action = llm(action_prompt, stop=["\n"], temperature=0.0).strip()
            if not action or ("Finish[" not in action and "Search[" not in action and "Lookup[" not in action):
                action = "Finish[null]"
        
        # Ensure action is a string and lowercase first char
        if not isinstance(action, str):
            action = str(action)
        action_lowercase = action[0].lower() + action[1:] if action else action
        
        # Execute action
        obs, r, done, info = env.step(action_lowercase)
        obs = obs.replace('\\n', '') if isinstance(obs, str) else str(obs)
        
        step_str = f"Thought {i}: {thought}\nAction {i}: {action}\nObservation {i}: {obs}\n"
        current_prompt += step_str
        trajectory_steps.append(step_str)
        
        if to_print:
            print(step_str)
        
        reward = r
        if done:
            answer = info.get('answer', 'null')
            break
    
    # Force finish if not done
    if not done:
        if to_print:
            print(f"[WARNING] Agent did not finish in 7 steps. Forcing Finish[null].")
        obs, r, done, info = env.step("finish[null]")
        answer = "null"
        trajectory_steps.append(f"Thought 8: Agent did not finish.\nAction 8: Finish[null]\nObservation 8: {obs}\n")
    
    # Get ground truth and LLM judge evaluation
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
        'n_calls': n_calls,
        'n_badcalls': n_badcalls,
        'traj': REACT_PROMPT + question + "\n" + "".join(trajectory_steps),
        'framework': 'react',
        'llm_correct': llm_eval['llm_correct'],
        'llm_explanation': llm_eval['llm_explanation']
    }
    
    if to_print:
        print(f"\n[RESULT] Answer: {answer}")
        print(f"[GT] {gt_answer}")
        print(f"[EM] {info_dict['em']} | [F1] {info_dict['f1']:.3f} | [LLM] {info_dict['llm_correct']}")
        print("=" * 60)
    
    return reward, info_dict
