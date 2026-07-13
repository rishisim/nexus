"""
Shared utilities for PopQA agents.

PopQA: Entity-centric open-domain QA with varying entity popularity.
"""

import os
import re
import json
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../shared')))
import wikienv
import wrappers
from llm import llm
from experiment_utils import step, append_to_json, EnvWrapper


# --- Environment Setup ---
env = None


def get_popqa_env():
    """Get or initialize the PopQA environment."""
    global env
    if env is None:
        env = wikienv.WikiEnv()
        env = wrappers.PopQAWrapper(env, split="test")
        env = wrappers.LoggingWrapper(env)
    return env


# --- Prompt Loading ---
PROMPT_FILE_PATH = './prompts/popqa.json'
WEBTHINK_PROMPT_TEMPLATE = ""

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, 'prompts', 'popqa.json')
    with open(prompt_path, 'r') as f:
        prompt_dict = json.load(f)
    instruction = """Solve a question answering task with interleaving Thought, Action, Observation steps. Thought can reason about the current situation, and Action can be three types:
(1) Search[entity], which searches the exact entity on Wikipedia and returns the first paragraph if it exists. If not, it will return some similar entities to search.
(2) Lookup[keyword], which returns the next sentence containing keyword in the current passage.
(3) Finish[answer], which returns the answer and finishes the task.
Here are some examples.
"""
    WEBTHINK_PROMPT_TEMPLATE = prompt_dict['webthink_simple3']
except FileNotFoundError:
    print(f"[ERROR] Prompt file not found at {PROMPT_FILE_PATH}")
    WEBTHINK_PROMPT_TEMPLATE = "Question: "
except KeyError:
    print(f"[ERROR] 'webthink_simple3' key not found in {PROMPT_FILE_PATH}")
    WEBTHINK_PROMPT_TEMPLATE = "Question: "


# --- Answer Extraction ---
def extract_final_answer_from_trace_string(trace_trajectory_string):
    """Extract the final answer from a trajectory string."""
    pattern = re.compile(r"^Action \d+: Finish\[(.*?)\]\s*$", re.MULTILINE)
    matches = pattern.findall(trace_trajectory_string)
    if matches:
        return matches[-1].strip()
    return None


def extract_answers_from_traces(all_traces_info):
    """Extract answers from a list of trace info dictionaries."""
    extracted_answers = []
    if not isinstance(all_traces_info, list):
        return extracted_answers

    for trace_info in all_traces_info:
        trajectory = trace_info.get('traj', '')
        answer_from_traj = extract_final_answer_from_trace_string(trajectory)
        if answer_from_traj is not None:
            extracted_answers.append(answer_from_traj)
        else:
            env_answer = trace_info.get('answer')
            if env_answer:
                extracted_answers.append(env_answer)
            else:
                extracted_answers.append(None)

    return [ans for ans in extracted_answers if ans is not None]


# --- LLM-as-Judge Evaluation ---
def llm_judge_answer(question, prediction, ground_truth):
    """Use LLM as a judge to evaluate semantic equivalence."""
    prompt = f"""You are an expert evaluator for a Question Answering system.

Question: {question}
Ground Truth Answer: {ground_truth}
Predicted Answer: {prediction}

Task: Determine if the "Predicted Answer" is semantically equivalent to the "Ground Truth Answer".

Guidelines:
- Ignore minor formatting differences (punctuation, capitalization)
- Allow for synonyms or different entity aliases (e.g., "JFK" = "John F. Kennedy")
- If the prediction adds extra correct context, it is ACCEPTABLE
- If the prediction is vague or missing key information, it is INCORRECT

Output:
Explanation: [Brief reasoning]
Label: [CORRECT or INCORRECT]"""

    response = llm(prompt, stop=[], num_traces=1)

    is_correct = "CORRECT" in response.upper() and "INCORRECT" not in response.upper()

    explanation = response.strip()
    if "Explanation:" in response:
        parts = response.split("Label:")
        explanation = parts[0].replace("Explanation:", "").strip() if parts else response.strip()

    return {
        'llm_correct': is_correct,
        'llm_explanation': explanation
    }


# --- Core Single Trace Execution ---
def run_single_trace(idx, initial_prompt_template, to_print=True, temperature=None):
    """Execute a single ReAct trace for a PopQA question."""
    popqa_env = get_popqa_env()

    question = popqa_env.reset(idx=idx)
    current_prompt = initial_prompt_template + question + "\n"

    if to_print:
        print(f"[TRACE] Index: {idx}")
        print(f"[QUESTION] {question}")

    n_calls, n_badcalls = 0, 0
    current_trace_steps = []
    done = False
    info = {}

    num_traces_param = 1 if temperature is None or temperature == 0.0 else 3

    for i in range(1, 8):
        n_calls += 1
        thought_action = llm(current_prompt + f"Thought {i}:", stop=[f"\nObservation {i}:"], num_traces=num_traces_param)

        try:
            thought, action = thought_action.strip().split(f"\nAction {i}: ")
        except:
            if to_print:
                print(f"[ERROR] Parsing thought/action: '{thought_action}'")
            n_badcalls += 1
            thought = thought_action.strip().split('\n')[0] if thought_action else "Error in thought generation"
            action_prompt = current_prompt + f"Thought {i}: {thought}\nAction {i}:"
            action = llm(action_prompt, stop=["\n"], num_traces=num_traces_param).strip()
            if not action or ("Finish[" not in action and "Search[" not in action and "Lookup[" not in action):
                action = "Finish[null]"
                if to_print:
                    print(f"[RECOVERY] Using default action: {action}")

        if not isinstance(action, str):
            action = str(action)

        action_lowercase = action[0].lower() + action[1:] if action else action
        obs, r, done, info = step(popqa_env, action_lowercase)
        obs = obs.replace('\\n', '') if isinstance(obs, str) else str(obs)

        step_str = f"Thought {i}: {thought}\nAction {i}: {action}\nObservation {i}: {obs}\n"
        current_prompt += step_str
        current_trace_steps.append(step_str)

        if to_print:
            print(step_str)

        if done:
            break

    if not isinstance(info, dict):
        info = {}

    if not done:
        if to_print:
            print(f"[WARNING] Agent did not finish in {i} steps. Forcing Finish[null].")
        obs_finish, r_finish, done_finish, info_finish = step(popqa_env, "finish[null]")
        info.update(info_finish)
        if 'answer' not in info or not info['answer']:
            info['answer'] = 'null'
        forced_step_str = f"Thought {i+1}: Agent did not finish. Forcing.\nAction {i+1}: Finish[null]\nObservation {i+1}: {obs_finish}\n"
        current_trace_steps.append(forced_step_str)

    answer = info.get('answer', 'null')
    gt_answer = info.get('gt_answer', '')
    question_text = question

    llm_eval = llm_judge_answer(question_text, answer, gt_answer)

    trace_info = info.copy()
    trace_info.update({
        'n_calls': n_calls,
        'n_badcalls': n_badcalls,
        'traj': initial_prompt_template + question + "\n" + "".join(current_trace_steps),
        'question_idx': idx,
        'question_text': question_text,
        'answer': answer,
        'llm_correct': llm_eval['llm_correct'],
        'llm_explanation': llm_eval['llm_explanation']
    })

    if to_print:
        print(f"[RESULT] Answer: {trace_info['answer']} | GT: {trace_info.get('gt_answer', 'UNKNOWN')} | EM: {trace_info.get('em', 0.0)} | LLM: {llm_eval['llm_correct']}\n")

    return trace_info
