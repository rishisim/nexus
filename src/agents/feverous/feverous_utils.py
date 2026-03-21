"""
Shared utilities for FEVEROUS agents.

This module contains common functions used by all FEVEROUS agent frameworks:
- LLM interaction
- Environment setup and interaction
- Prompt loading
- Answer extraction and synthesis
"""

import os
import time
import re
import json
import sys
import requests
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Add shared directory to path for wikienv and wrappers
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../shared')))
import wrappers
from llm import llm
from experiment_utils import step, append_to_json, EnvWrapper

# Import the FEVEROUS-specific environment
from feverous_env import FeverousEnv


# --- Environment Setup ---
env = None


def get_feverous_env():
    """Get or initialize the FEVEROUS environment."""
    global env
    if env is None:
        feverous_env = FeverousEnv()
        env = wrappers.FeverousWrapper(feverous_env, split="dev")
        env = wrappers.LoggingWrapper(env)
    return env


# --- Prompt Loading ---
PROMPT_FILE_PATH = './prompts/feverous.json'
WEBTHINK_PROMPT_TEMPLATE = ""

try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(script_dir, 'prompts', 'feverous.json')
    with open(prompt_path, 'r') as f:
        prompt_dict = json.load(f)
    WEBTHINK_PROMPT_TEMPLATE = prompt_dict['webthink_simple3']
except FileNotFoundError:
    print(f"[ERROR] Prompt file not found at {PROMPT_FILE_PATH}")
    print("Please ensure 'feverous.json' is in the 'prompts/' directory.")
    # Fallback prompt with table support
    WEBTHINK_PROMPT_TEMPLATE = """Solve a fact verification task with interleaving Thought, Action, Observation steps. Thought can reason about the current situation. Actions can be:
(1) Search[entity]: Search for a Wikipedia page about the entity.
(2) Lookup[keyword]: Find text on the current page containing the keyword.
(3) TableLookup[query]: Look up table content. Query can be a table index (0, 1, ...) or search term.
(4) Finish[verdict]: Submit final answer. Verdict must be SUPPORTS, REFUTES, or NOT ENOUGH INFO.

Claim: {claim}
"""
except KeyError:
    print(f"[ERROR] 'webthink_simple3' key not found in {PROMPT_FILE_PATH}")
    WEBTHINK_PROMPT_TEMPLATE = "Claim: {claim}\n"


# --- Answer Extraction ---
def extract_final_answer_from_trace_string(trace_trajectory_string):
    """
    Extract the final answer from a trajectory string.
    
    Args:
        trace_trajectory_string: Full trajectory text
        
    Returns:
        Answer string (SUPPORTS/REFUTES/NOT ENOUGH INFO) or None
    """
    matches = re.findall(r'[Ff]inish\[([^\]]+)\]', trace_trajectory_string)
    if matches:
        answer = matches[-1].strip().upper()
        if answer.startswith("SUPPORT"):
            return "SUPPORTS"
        elif answer.startswith("REFUTE"):
            return "REFUTES"
        elif "NOT ENOUGH" in answer:
            return "NOT ENOUGH INFO"
        return answer
    return None


def extract_answers_from_traces(all_traces_info):
    """
    Extract answers from a list of trace info dictionaries.
    
    Args:
        all_traces_info: List of trace info dicts
        
    Returns:
        List of answer strings (filtering out None values)
    """
    extracted_answers = []
    if not isinstance(all_traces_info, list):
        print(f"[WARNING] extract_answers_from_traces expected a list, got {type(all_traces_info)}")
        return extracted_answers

    for i, trace_info in enumerate(all_traces_info):
        trajectory = trace_info.get('traj', '')
        answer_from_traj = extract_final_answer_from_trace_string(trajectory)

        if answer_from_traj is not None:
            extracted_answers.append(answer_from_traj)
        else:
            env_answer = trace_info.get('answer')
            if env_answer is not None:
                normalized = env_answer.strip().upper()
                if normalized.startswith("SUPPORT"):
                    extracted_answers.append("SUPPORTS")
                elif normalized.startswith("REFUTE"):
                    extracted_answers.append("REFUTES")
                elif "NOT ENOUGH" in normalized:
                    extracted_answers.append("NOT ENOUGH INFO")
                else:
                    extracted_answers.append(None)
            else:
                extracted_answers.append(None)

    return [ans for ans in extracted_answers if ans is not None]


# --- Core Single Trace Execution ---
def run_single_trace(idx, initial_prompt_template, to_print=True, temperature=None):
    """
    Execute a single ReAct trace for a FEVEROUS claim.
    
    Args:
        idx: Question index
        initial_prompt_template: The prompt template to use
        to_print: Whether to print progress
        temperature: Override temperature (if None, uses default based on single trace)
        
    Returns:
        Dictionary with trace information including:
        - question_idx, question_text, answer, gt_answer
        - em, f1, reward
        - n_calls, n_badcalls
        - traj (full trajectory string)
    """
    feverous_env = get_feverous_env()
    
    question = feverous_env.reset(idx=idx)
    current_prompt = initial_prompt_template + question + "\n"
    
    if to_print:
        try:
            print(f"[TRACE] Index: {idx}")
            print(f"[CLAIM] {question}")
        except UnicodeEncodeError:
            print(f"[TRACE] Index: {idx}")
            print(f"[CLAIM] {question}".encode('ascii', 'replace').decode('ascii'))
    
    n_calls, n_badcalls = 0, 0
    current_trace_steps = []
    
    # Determine num_traces parameter for LLM (affects temperature)
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
            if not action or ("Finish[" not in action and "Search[" not in action and "Lookup[" not in action and "TableLookup[" not in action):
                action = "Finish[NOT ENOUGH INFO]"
                if to_print:
                    print(f"[RECOVERY] Using default action: {action}")
        
        # Ensure action is a string
        if not isinstance(action, str):
            action = str(action)
        
        # Lowercase first character of action (e.g., Search -> search)
        # Handle table_lookup action as well
        action_lowercase = action[0].lower() + action[1:] if action else action
        
        # Convert TableLookup to table_lookup for environment
        if action_lowercase.startswith("tableLookup["):
            action_lowercase = "table_lookup[" + action_lowercase[len("tableLookup["):]
        
        obs, r, done, info = step(feverous_env, action_lowercase)
        obs = obs.replace('\\n', '') if isinstance(obs, str) else str(obs)
        
        step_str = f"Thought {i}: {thought}\nAction {i}: {action}\nObservation {i}: {obs}\n"
        current_prompt += step_str
        current_trace_steps.append(step_str)
        
        if to_print:
            try:
                print(step_str)
            except UnicodeEncodeError:
                print(step_str.encode('ascii', 'replace').decode('ascii'))
        
        if done:
            break
    
    if not isinstance(info, dict):
        info = {}
    
    if not done:
        if to_print:
            print(f"[WARNING] Agent did not finish in {i} steps. Forcing Finish[NOT ENOUGH INFO].")
        obs_finish, r_finish, done_finish, info_finish = step(feverous_env, "finish[NOT ENOUGH INFO]")
        info.update(info_finish)
        if 'answer' not in info or not info['answer']:
            info['answer'] = 'NOT ENOUGH INFO'
        forced_step_str = f"Thought {i+1}: Agent did not finish. Forcing.\nAction {i+1}: Finish[NOT ENOUGH INFO]\nObservation {i+1}: {obs_finish}\n"
        current_trace_steps.append(forced_step_str)
    
    trace_info = info.copy()
    trace_info.update({
        'n_calls': n_calls,
        'n_badcalls': n_badcalls,
        'traj': initial_prompt_template + question + "\n" + "".join(current_trace_steps),
        'question_idx': idx,
        'question_text': question,
        'answer': info.get('answer', 'NOT ENOUGH INFO' if not done else '[ERROR_NO_ANSWER]')
    })
    
    if to_print:
        print(f"[RESULT] Answer: {trace_info['answer']} | GT: {trace_info.get('gt_answer', 'UNKNOWN')} | EM: {trace_info.get('em', 0.0)}\n")
    
    return trace_info
