"""
Shared utilities for HoVer agents.

HoVer: Multi-hop claim verification (SUPPORTED/NOT_SUPPORTED), filtered to 2-hop.
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


def get_hover_env():
    """Get or initialize the HoVer environment."""
    global env
    if env is None:
        env = wikienv.WikiEnv()
        env = wrappers.HoVerWrapper(env, split="dev")
        env = wrappers.LoggingWrapper(env)
    return env


# --- Prompt Loading ---
PROMPT_FILE_PATH = './prompts/hover.json'
WEBTHINK_PROMPT_TEMPLATE = ""

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, 'prompts', 'hover.json')
    with open(prompt_path, 'r') as f:
        prompt_dict = json.load(f)
    WEBTHINK_PROMPT_TEMPLATE = prompt_dict['webthink_simple3']
except FileNotFoundError:
    print(f"[ERROR] Prompt file not found at {PROMPT_FILE_PATH}")
    WEBTHINK_PROMPT_TEMPLATE = "Claim: "
except KeyError:
    print(f"[ERROR] 'webthink_simple3' key not found in {PROMPT_FILE_PATH}")
    WEBTHINK_PROMPT_TEMPLATE = "Claim: "


# --- Answer Extraction ---
def extract_final_answer_from_trace_string(trace_trajectory_string):
    """Extract the final answer (SUPPORTED/NOT_SUPPORTED) from a trajectory string."""
    matches = re.findall(r'[Ff]inish\[([^\]]+)\]', trace_trajectory_string)
    if matches:
        answer = matches[-1].strip().upper()
        # Normalize: handle various forms
        if "NOT" in answer and "SUPPORT" in answer:
            return "NOT_SUPPORTED"
        elif "SUPPORT" in answer:
            return "SUPPORTED"
        return answer
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
                normalized = env_answer.strip().upper().replace(" ", "_")
                if "NOT" in normalized and "SUPPORT" in normalized:
                    extracted_answers.append("NOT_SUPPORTED")
                elif "SUPPORT" in normalized:
                    extracted_answers.append("SUPPORTED")
                else:
                    extracted_answers.append(None)
            else:
                extracted_answers.append(None)

    return [ans for ans in extracted_answers if ans is not None]


# --- Core Single Trace Execution ---
def run_single_trace(idx, initial_prompt_template, to_print=True, temperature=None):
    """Execute a single ReAct trace for a HoVer claim."""
    hover_env = get_hover_env()

    question = hover_env.reset(idx=idx)
    current_prompt = initial_prompt_template + question + "\n"

    if to_print:
        print(f"[TRACE] Index: {idx}")
        print(f"[CLAIM] {question}")

    n_calls, n_badcalls = 0, 0
    current_trace_steps = []
    done = False
    info = {}

    num_traces_param = 1 if temperature is None or temperature == 0.0 else 3

    for i in range(1, 8):  # Max 7 steps per trace
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
                action = "Finish[NOT_SUPPORTED]"
                if to_print:
                    print(f"[RECOVERY] Using default action: {action}")

        if not isinstance(action, str):
            action = str(action)

        action_lowercase = action[0].lower() + action[1:] if action else action
        obs, r, done, info = step(hover_env, action_lowercase)
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
            print(f"[WARNING] Agent did not finish in {i} steps. Forcing Finish[NOT_SUPPORTED].")
        obs_finish, r_finish, done_finish, info_finish = step(hover_env, "finish[NOT_SUPPORTED]")
        info.update(info_finish)
        if 'answer' not in info or not info['answer']:
            info['answer'] = 'NOT_SUPPORTED'
        forced_step_str = f"Thought {i+1}: Agent did not finish. Forcing.\nAction {i+1}: Finish[NOT_SUPPORTED]\nObservation {i+1}: {obs_finish}\n"
        current_trace_steps.append(forced_step_str)

    trace_info = info.copy()
    trace_info.update({
        'n_calls': n_calls,
        'n_badcalls': n_badcalls,
        'traj': initial_prompt_template + question + "\n" + "".join(current_trace_steps),
        'question_idx': idx,
        'question_text': question,
        'answer': info.get('answer', 'NOT_SUPPORTED' if not done else '[ERROR_NO_ANSWER]')
    })

    if to_print:
        print(f"[RESULT] Answer: {trace_info['answer']} | GT: {trace_info.get('gt_answer', 'UNKNOWN')} | EM: {trace_info.get('em', 0.0)}\n")

    return trace_info
