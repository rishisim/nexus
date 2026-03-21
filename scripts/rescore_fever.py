#!/usr/bin/env python3
"""
Re-score existing FEVER traces using the fixed extraction and normalization logic.

Quantifies the impact of the "NOT ENOUGH INFORMATION" vs "NOT ENOUGH INFO" bug
by re-extracting and re-scoring existing traces without needing to re-run experiments.
"""

import json
import re
import string
import os
import sys


def normalize_answer_fixed(s):
    """Fixed normalize_answer that handles label equivalences."""
    def remove_articles(text):
        return re.sub(r"\b(a|an|the)\b", " ", text)
    def white_space_fix(text):
        return " ".join(text.split())
    def remove_punc(text):
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)
    def lower(text):
        return text.lower()

    result = white_space_fix(remove_articles(remove_punc(lower(s))))
    LABEL_EQUIVALENCES = {"not enough information": "not enough info"}
    return LABEL_EQUIVALENCES.get(result, result)


def normalize_answer_old(s):
    """Original normalize_answer (buggy - doesn't handle INFO vs INFORMATION)."""
    def remove_articles(text):
        return re.sub(r"\b(a|an|the)\b", " ", text)
    def white_space_fix(text):
        return " ".join(text.split())
    def remove_punc(text):
        exclude = set(string.punctuation)
        return "".join(ch for ch in text if ch not in exclude)
    def lower(text):
        return text.lower()
    return white_space_fix(remove_articles(remove_punc(lower(s))))


def extract_answer_fixed(trace_string):
    """Fixed extraction that handles case variations and abbreviation differences."""
    matches = re.findall(r'[Ff]inish\[([^\]]+)\]', trace_string)
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


def extract_answer_old(trace_string):
    """Original strict extraction."""
    pattern = re.compile(r"^Action \d+: Finish\[(SUPPORTS|REFUTES|NOT ENOUGH INFO)\]\s*$", re.MULTILINE)
    matches = pattern.findall(trace_string)
    if matches:
        return matches[-1].strip()
    return None


def rescore_results(results_path):
    """Re-score a FEVER results file and compare old vs new scores."""
    with open(results_path) as f:
        data = json.load(f)

    print(f"\n{'='*70}")
    print(f"Re-scoring: {results_path}")
    print(f"Total examples: {len(data)}")
    print(f"{'='*70}")

    old_correct = 0
    new_correct = 0
    flipped = []  # Cases that change from wrong to right

    for i, item in enumerate(data):
        gt = item.get('gt_answer', item.get('label', ''))
        old_answer = item.get('answer', '')
        traj = item.get('traj', '')
        old_em = item.get('em', 0)

        # Re-extract from trajectory
        new_answer = extract_answer_fixed(traj)
        if new_answer is None:
            new_answer = old_answer  # Fall back to stored answer

        # Score with old method
        if old_answer and gt:
            old_match = normalize_answer_old(gt) == normalize_answer_old(old_answer)
        else:
            old_match = False

        # Score with new method
        if new_answer and gt:
            new_match = normalize_answer_fixed(gt) == normalize_answer_fixed(new_answer)
        else:
            new_match = False

        if old_match:
            old_correct += 1
        if new_match:
            new_correct += 1

        if new_match and not old_match:
            flipped.append({
                'idx': i,
                'gt': gt,
                'old_answer': old_answer,
                'new_answer': new_answer,
                'old_em': old_em,
            })

    total = len(data)
    print(f"\nOld scoring: {old_correct}/{total} = {old_correct/total:.1%}")
    print(f"New scoring: {new_correct}/{total} = {new_correct/total:.1%}")
    print(f"Flipped (wrong→right): {len(flipped)}")

    if flipped:
        print(f"\nFlipped examples:")
        for f in flipped[:10]:
            print(f"  idx={f['idx']}: GT='{f['gt']}', old='{f['old_answer']}', new='{f['new_answer']}'")
        if len(flipped) > 10:
            print(f"  ... and {len(flipped)-10} more")

    return old_correct, new_correct, total


def main():
    results_dir = os.path.join(os.path.dirname(__file__), '..', 'results', 'fever')

    # Find all result directories
    result_dirs = sorted([
        d for d in os.listdir(results_dir)
        if os.path.isdir(os.path.join(results_dir, d))
    ])

    print("FEVER Re-scoring Report")
    print("=" * 70)
    print("Comparing old (buggy) vs new (fixed) scoring for all FEVER results")

    for dirname in result_dirs:
        dirpath = os.path.join(results_dir, dirname)

        for framework in ['react', 'nexus']:
            results_file = os.path.join(dirpath, f'{framework}.json')
            if os.path.exists(results_file):
                try:
                    rescore_results(results_file)
                except Exception as e:
                    print(f"\n[ERROR] Failed to process {results_file}: {e}")


if __name__ == '__main__':
    main()
