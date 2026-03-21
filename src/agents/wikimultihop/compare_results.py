"""
Generate comparison statistics for Nexus vs ReAct on 2WikiMultiHop
"""

import json
import os

# Load results
nexus_file = "results/wikimultihop/nexus_test_20260119_152221.json"
react_file = "results/wikimultihop/react_test_20260119_154753.json"

with open(nexus_file) as f:
    nexus_data = json.load(f)

with open(react_file) as f:
    react_data = json.load(f)

# Task types
task_types = ['bridge_comparison', 'comparison', 'compositional', 'inference']

# Calculate stats per task type
def calculate_stats(data):
    stats = {}
    for task_type in task_types:
        type_results = [r for r in data['results'] if r.get('question_type') == task_type]
        total = len(type_results)
        correct = sum(1 for r in type_results if r.get('llm_correct', False))
        total_calls = sum(r.get('n_calls', 0) for r in type_results)
        calls_per_success = total_calls / correct if correct > 0 else float('inf')
        
        stats[task_type] = {
            'correct': correct,
            'total': total,
            'accuracy': correct / total * 100 if total > 0 else 0,
            'total_calls': total_calls,
            'avg_calls': total_calls / total if total > 0 else 0,
            'calls_per_success': calls_per_success
        }
    
    # Overall
    all_results = data['results']
    total = len(all_results)
    correct = sum(1 for r in all_results if r.get('llm_correct', False))
    total_calls = sum(r.get('n_calls', 0) for r in all_results)
    
    stats['overall'] = {
        'correct': correct,
        'total': total,
        'accuracy': correct / total * 100 if total > 0 else 0,
        'total_calls': total_calls,
        'avg_calls': total_calls / total if total > 0 else 0,
        'calls_per_success': total_calls / correct if correct > 0 else float('inf')
    }
    
    return stats

nexus_stats = calculate_stats(nexus_data)
react_stats = calculate_stats(react_data)

# Print comparison table
print("=" * 100)
print("2WikiMultiHop Results Comparison: Nexus vs ReAct")
print("=" * 100)
print()

# Header
header = f"{'Task Type':<22} | {'Nexus':^15} | {'ReAct':^15} | {'Nexus Calls':^12} | {'ReAct Calls':^12} | {'Nexus C/S':^10} | {'ReAct C/S':^10}"
print(header)
print("-" * 100)

# Data rows
for task_type in task_types:
    ns = nexus_stats[task_type]
    rs = react_stats[task_type]
    nexus_acc = f"{ns['correct']}/{ns['total']} ({ns['accuracy']:.0f}%)"
    react_acc = f"{rs['correct']}/{rs['total']} ({rs['accuracy']:.0f}%)"
    nexus_calls = f"{ns['total_calls']}"
    react_calls = f"{rs['total_calls']}"
    nexus_cps = f"{ns['calls_per_success']:.2f}"
    react_cps = f"{rs['calls_per_success']:.2f}"
    
    print(f"{task_type:<22} | {nexus_acc:^15} | {react_acc:^15} | {nexus_calls:^12} | {react_calls:^12} | {nexus_cps:^10} | {react_cps:^10}")

print("-" * 100)

# Overall
ns = nexus_stats['overall']
rs = react_stats['overall']
nexus_acc = f"{ns['correct']}/{ns['total']} ({ns['accuracy']:.0f}%)"
react_acc = f"{rs['correct']}/{rs['total']} ({rs['accuracy']:.0f}%)"
nexus_calls = f"{ns['total_calls']}"
react_calls = f"{rs['total_calls']}"
nexus_cps = f"{ns['calls_per_success']:.2f}"
react_cps = f"{rs['calls_per_success']:.2f}"

print(f"{'OVERALL':<22} | {nexus_acc:^15} | {react_acc:^15} | {nexus_calls:^12} | {react_calls:^12} | {nexus_cps:^10} | {react_cps:^10}")
print("=" * 100)
print()
print("Legend:")
print("  C/S = LLM Calls per Success (lower is more efficient)")
print()

# Summary
print("Summary:")
print(f"  - Nexus: {nexus_stats['overall']['correct']}/{nexus_stats['overall']['total']} correct, {nexus_stats['overall']['total_calls']} total LLM calls, {nexus_stats['overall']['calls_per_success']:.2f} calls per success")
print(f"  - ReAct: {react_stats['overall']['correct']}/{react_stats['overall']['total']} correct, {react_stats['overall']['total_calls']} total LLM calls, {react_stats['overall']['calls_per_success']:.2f} calls per success")
