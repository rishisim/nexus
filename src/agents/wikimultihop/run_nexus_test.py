"""
Test Script: Run Nexus on 2WikiMultiHop Dataset

This script runs the Nexus agent on 5 tasks from each task type in the 
2WikiMultiHop train dataset and outputs detailed logs.

Task Types:
- bridge_comparison
- comparison
- compositional
- inference
"""

import os
import sys
import json
from datetime import datetime

# Add paths for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from wikimultihop_utils import WikiMultiHopEnv
from nexus_wrapper import run_nexus


import argparse

TASK_TYPES = ['bridge_comparison', 'comparison', 'compositional', 'inference']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks-per-type', type=int, default=5)
    args = parser.parse_args()
    TASKS_PER_TYPE = args.tasks_per_type
    print("=" * 70)
    print("2WikiMultiHop - Nexus Agent Test")
    print(f"Running {TASKS_PER_TYPE} tasks per type, {len(TASK_TYPES)} types total")
    print(f"Start time: {datetime.now().isoformat()}")
    print("=" * 70)
    
    # Initialize environment
    env = WikiMultiHopEnv(split="train")
    
    # Results storage
    all_results = []
    summary_by_type = {t: {'correct': 0, 'total': 0} for t in TASK_TYPES}
    
    # Create results directory
    results_dir = os.path.abspath(os.path.join(
        os.path.dirname(__file__), 
        '../../../results/wikimultihop'
    ))
    os.makedirs(results_dir, exist_ok=True)
    
    # Run tests for each task type
    for task_type in TASK_TYPES:
        print(f"\n{'#' * 70}")
        print(f"# TASK TYPE: {task_type.upper()}")
        print(f"{'#' * 70}")
        
        # Get indices for this task type
        indices = env.get_indices_by_type(task_type, limit=TASKS_PER_TYPE)
        
        if len(indices) < TASKS_PER_TYPE:
            print(f"[WARNING] Only found {len(indices)} tasks for type '{task_type}'")
        
        for i, idx in enumerate(indices):
            print(f"\n--- Task {i+1}/{len(indices)} (Index: {idx}) ---")
            
            try:
                reward, info = run_nexus(env, idx, to_print=True)
                all_results.append(info)
                
                # Update summary
                summary_by_type[task_type]['total'] += 1
                if info['llm_correct']:
                    summary_by_type[task_type]['correct'] += 1
                    
            except Exception as e:
                print(f"[ERROR] Failed to run task {idx}: {e}")
                import traceback
                traceback.print_exc()
                all_results.append({
                    'question_idx': idx,
                    'question_type': task_type,
                    'error': str(e),
                    'framework': 'nexus'
                })
                summary_by_type[task_type]['total'] += 1
    
    # Print final summary
    print("\n" + "=" * 70)
    print("FINAL SUMMARY")
    print("=" * 70)
    
    total_correct = 0
    total_tasks = 0
    
    for task_type in TASK_TYPES:
        stats = summary_by_type[task_type]
        accuracy = stats['correct'] / stats['total'] * 100 if stats['total'] > 0 else 0
        print(f"  {task_type:20s}: {stats['correct']}/{stats['total']} ({accuracy:.1f}%)")
        total_correct += stats['correct']
        total_tasks += stats['total']
    
    overall_accuracy = total_correct / total_tasks * 100 if total_tasks > 0 else 0
    print("-" * 40)
    print(f"  {'OVERALL':20s}: {total_correct}/{total_tasks} ({overall_accuracy:.1f}%)")
    print("=" * 70)
    
    # Save results to JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = os.path.join(results_dir, f"nexus_test_{timestamp}.json")
    
    output = {
        'metadata': {
            'timestamp': datetime.now().isoformat(),
            'tasks_per_type': TASKS_PER_TYPE,
            'task_types': TASK_TYPES,
            'framework': 'nexus',
            'dataset': '2WikiMultiHop',
            'split': 'train'
        },
        'summary': summary_by_type,
        'overall': {
            'correct': total_correct,
            'total': total_tasks,
            'accuracy': overall_accuracy
        },
        'results': all_results
    }
    
    with open(results_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n[SAVED] Results saved to: {results_file}")
    print(f"End time: {datetime.now().isoformat()}")


if __name__ == "__main__":
    main()
