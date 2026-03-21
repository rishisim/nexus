"""
Verification-Guided ReAct Agent for FEVER (inspired by Reflexion)

Runs a ReAct trace, then verifies the answer using LLM. If the verification
determines the answer is incorrect, runs a second trace with verification
feedback to guide the reasoning. Note: this is a simplified single-retry
approach, not the full Reflexion algorithm from Shinn et al. 2023 (which
maintains a persistent reflection memory across multiple trials).
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import json

from fever_utils import (
    run_single_trace,
    llm,
    WEBTHINK_PROMPT_TEMPLATE
)
from wrappers import normalize_answer


def load_verification_prompt():
    """Load the reflexion verification prompt from JSON file."""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(script_dir, 'prompts', 'fever_reflexion.json')
        with open(prompt_path, 'r') as f:
            prompts = json.load(f)
        return prompts['reflexion_verification']
    except (FileNotFoundError, KeyError) as e:
        print(f"[WARNING] Could not load verification prompt: {e}")
        return """You will be given a reasoning trace and its final answer. Analyze whether the answer is correct based on the evidence.
Respond with:
Verification: [CORRECT or INCORRECT]
Reasoning: [Brief explanation]"""


def verify_answer(trajectory_info, verification_prompt, to_print=False):
    """
    Verify if the answer in the trajectory is correct using LLM.
    
    Args:
        trajectory_info: Dictionary with trajectory information
        verification_prompt: The verification prompt template
        to_print: Whether to print the verification
        
    Returns:
        Dictionary with verification results:
        - verification_status: 'CORRECT' or 'INCORRECT'
        - verification_reasoning: Explanation and guidance from the LLM
    """
    # Extract trajectory string
    if isinstance(trajectory_info, dict):
        trajectory_str = trajectory_info.get('traj', '')
        if not trajectory_str:
            # Fallback: reconstruct from available info
            question = trajectory_info.get('question_text', '')
            answer = trajectory_info.get('answer', '')
            trajectory_str = f"Claim: {question}\n[Trajectory details not available]\nFinal Answer: {answer}"
    else:
        trajectory_str = str(trajectory_info)
    
    # Create full prompt for verification
    full_prompt = f"{verification_prompt}\n\nNow verify this reasoning trace:\n\n{trajectory_str}\n\nVerification:"
    
    # Generate verification using LLM
    try:
        verification_response = llm(full_prompt, stop=[], num_traces=1)
        
        # Parse the verification response
        verification_status = "UNKNOWN"
        verification_reasoning = verification_response.strip()
        
        # Try to extract CORRECT or INCORRECT from the response
        if "CORRECT" in verification_response.upper():
            if "INCORRECT" in verification_response.upper():
                # Both appear, check which comes first after "Verification:"
                if verification_response.upper().find("VERIFICATION:") != -1:
                    after_label = verification_response[verification_response.upper().find("VERIFICATION:") + len("VERIFICATION:"):]
                    if after_label.strip().upper().startswith("CORRECT"):
                        verification_status = "CORRECT"
                    elif after_label.strip().upper().startswith("INCORRECT"):
                        verification_status = "INCORRECT"
            else:
                verification_status = "CORRECT"
        elif "INCORRECT" in verification_response.upper():
            verification_status = "INCORRECT"
        
        # Try to extract reasoning portion
        if "Reasoning:" in verification_response:
            verification_reasoning = verification_response.split("Reasoning:")[-1].strip()
        
        if to_print:
            print(f"[VERIFICATION] Status: {verification_status}")
            print(f"[VERIFICATION] Reasoning: {verification_reasoning}")
        
        return {
            'verification_status': verification_status,
            'verification_reasoning': verification_reasoning,
            'full_verification_response': verification_response
        }
    except Exception as e:
        if to_print:
            print(f"[ERROR] Error during verification: {e}")
        return {
            'verification_status': 'ERROR',
            'verification_reasoning': f'Error during verification: {str(e)}',
            'full_verification_response': ''
        }


def run_reflexion_react(idx, prompt_template=None, to_print=True):
    """
    Run Reflexion ReAct with verification-driven second trace.
    
    Process:
    1. Run initial ReAct trace
    2. Verify the answer using LLM (reflexion verification)
    3. If INCORRECT, run second ReAct trace with verification feedback as context
    4. Return final answer (from trace 2 if run, otherwise trace 1)
    
    Args:
        idx: Question index from FEVER dataset
        prompt_template: Custom prompt template (uses default if None)
        to_print: Whether to print progress during execution
        
    Returns:
        Tuple of (reward, info_dict) where:
        - reward: EM score of the final answer
        - info_dict: Dictionary with both traces and verification results
    """
    if prompt_template is None:
        prompt_template = WEBTHINK_PROMPT_TEMPLATE
    
    # Load verification prompt
    verification_prompt = load_verification_prompt()
    
    if to_print:
        print("="*60)
        print("[FRAMEWORK] Reflexion ReAct (Verification-Driven)")
        print("="*60)
    
    # --- Trace 1: Initial attempt ---
    if to_print:
        print("\n--- Trace 1: Initial Attempt ---")
    
    trace_1 = run_single_trace(
        idx=idx,
        initial_prompt_template=prompt_template,
        to_print=to_print,
        temperature=0.0
    )
    
    question_text = trace_1.get('question_text')
    gt_answer = trace_1.get('gt_answer')
    
    if to_print:
        print(f"[TRACE 1] Answer: {trace_1.get('answer')}")
    
    # --- Generate Verification ---
    if to_print:
        print(f"\n{'='*60}")
        print("[VERIFICATION] Verifying Trace 1...")
    
    verification_result = verify_answer(trace_1, verification_prompt, to_print=to_print)
    
    # --- Conditional Trace 2: Run if verification is INCORRECT ---
    trace_2 = None
    num_traces_run = 1
    
    if verification_result['verification_status'] == 'INCORRECT':
        if to_print:
            print(f"\n{'='*60}")
            print("--- Trace 2: With Verification Feedback ---")
        
        # Create context with verification feedback
        feedback_context = f"""Previous attempt analysis:
You previously attempted this claim and concluded with: {trace_1.get('answer')}
However, this answer was incorrect.

Verification feedback: {verification_result['verification_reasoning']}

Use this feedback to guide your search and reasoning in this attempt.

"""
        
        modified_prompt = feedback_context + prompt_template
        
        trace_2 = run_single_trace(
            idx=idx,
            initial_prompt_template=modified_prompt,
            to_print=to_print,
            temperature=0.0
        )
        
        if to_print:
            print(f"[TRACE 2] Answer: {trace_2.get('answer')}")
        
        final_answer = trace_2.get('answer')
        num_traces_run = 2
    else:
        # Verification says CORRECT, use trace 1 answer
        final_answer = trace_1.get('answer')
        if to_print:
            print(f"[VERIFICATION] Answer is correct, no second trace needed.")
    
    # Calculate metrics based on final answer (using normalized comparison)
    em_score = 1.0 if normalize_answer(final_answer) == normalize_answer(gt_answer) else 0.0
    
    # Aggregate call counts
    total_calls = trace_1.get('n_calls', 0) + 1  # +1 for verification
    total_badcalls = trace_1.get('n_badcalls', 0)
    
    if trace_2:
        total_calls += trace_2.get('n_calls', 0)
        total_badcalls += trace_2.get('n_badcalls', 0)
    
    info_dict = {
        'question_idx': idx,
        'question_text': question_text,
        'answer': final_answer,
        'gt_answer': gt_answer,
        'em': em_score,
        'f1': em_score,
        'reward': em_score,
        'n_calls': total_calls,
        'n_badcalls': total_badcalls,
        'num_traces_run': num_traces_run,
        'verification': verification_result,
        'trace_1': {
            'answer': trace_1.get('answer'),
            'em': trace_1.get('em', 0.0),
            'n_calls': trace_1.get('n_calls', 0),
            'traj': trace_1.get('traj', '')
        },
        'trace_2': {
            'answer': trace_2.get('answer'),
            'em': trace_2.get('em', 0.0),
            'n_calls': trace_2.get('n_calls', 0),
            'traj': trace_2.get('traj', '')
        } if trace_2 else None,
        'full_trace_1': trace_1,
        'full_trace_2': trace_2,
        'framework': 'reflexion_react'
    }
    
    if to_print:
        print("="*60)
        print(f"[FINAL] Answer: {final_answer} | GT: {gt_answer} | EM: {em_score}")
        print(f"[TRACES] Ran {num_traces_run} trace(s)")
        print(f"[VERIFICATION] {verification_result['verification_status']}")
        print("="*60)
    
    return em_score, info_dict


if __name__ == '__main__':
    # Test with a sample FEVER example
    print("\n[TEST] Running Reflexion ReAct agent test\n")
    reward, info = run_reflexion_react(idx=3687, to_print=True)
    print(f"\n[TEST RESULT] Reward: {reward}, Final Answer: {info['answer']}")
    print(f"[TRACES RUN] {info['num_traces_run']}")
    print(f"[TRACE 1] Answer: {info['trace_1']['answer']}")
    if info['trace_2']:
        print(f"[TRACE 2] Answer: {info['trace_2']['answer']}")
    print(f"[VERIFICATION STATUS] {info['verification']['verification_status']}")
    print(f"[VERIFICATION REASONING] {info['verification']['verification_reasoning']}")
