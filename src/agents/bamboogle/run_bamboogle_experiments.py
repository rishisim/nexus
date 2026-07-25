"""
Bamboogle Experiment Runner with Continuation System
"""

import os
import sys
import json
import random
import argparse
from datetime import datetime
from typing import List, Dict, Any, Set
from pathlib import Path

from bamboogle_utils import WEBTHINK_PROMPT_TEMPLATE
from react_agent import run_react
from nexus_wrapper import run_nexus


class BamboogleExperimentRunner:

    FRAMEWORK_MAP = {
        'react': run_react,
        'nexus': run_nexus,
    }

    def __init__(
        self,
        model: str = "gemini-2.5-flash",
        num_examples: int = 5,
        frameworks: List[str] = None,
        results_base_dir: str = "../../../results/bamboogle",
        seed: int = 42,
        retry_failed: bool = False
    ):
        self.model = model
        self.num_examples = num_examples
        self.frameworks = frameworks or ['react']
        self.seed = seed
        self.retry_failed = retry_failed
        self.max_dev_examples = 125  # Bamboogle has only 125 examples

        run_name = f"seed{seed}_{model.replace('/', '-')}"
        script_dir = Path(__file__).parent
        self.results_dir = (script_dir / results_base_dir / run_name).resolve()
        self.results_dir.mkdir(parents=True, exist_ok=True)

        print("="*70, flush=True)
        print(f"[EXPERIMENT] Bamboogle Agent Evaluation", flush=True)
        print("="*70, flush=True)
        print(f"Results directory: {self.results_dir}", flush=True)
        print(f"Seed: {seed}", flush=True)
        print(f"Model: {model}", flush=True)
        print(f"Frameworks: {', '.join(self.frameworks)}", flush=True)
        print(f"Examples to run: {num_examples}", flush=True)
        print(f"Retry failed: {retry_failed}", flush=True)
        print("="*70, flush=True)

        self.config_path = self.results_dir / "config.json"
        self.processed_indices_path = self.results_dir / "processed_indices.json"
        self.failed_indices_path = self.results_dir / "failed_indices.json"
        self.run_history_path = self.results_dir / "run_history.json"

        self.config = self._load_or_create_config()
        self.results = {fw: [] for fw in self.frameworks}
        self._load_existing_results()

    def _load_or_create_config(self) -> Dict:
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            print(f"[CONFIG] Loaded existing config from previous runs")
            return config
        else:
            config = {
                "seed": self.seed,
                "model": self.model,
                "dataset": "bamboogle",
                "max_dev_examples": self.max_dev_examples,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            return config

    def _load_existing_results(self):
        for framework in self.frameworks:
            result_path = self.results_dir / f"{framework}.json"
            if result_path.exists():
                with open(result_path, 'r', encoding='utf-8') as f:
                    self.results[framework] = json.load(f)
                print(f"[LOAD] Found {len(self.results[framework])} existing results for {framework}")

    def load_processed_indices(self) -> Set[int]:
        if not self.processed_indices_path.exists():
            return set()
        with open(self.processed_indices_path, 'r', encoding='utf-8') as f:
            return set(json.load(f))

    def load_failed_indices(self) -> Set[int]:
        if not self.failed_indices_path.exists():
            return set()
        with open(self.failed_indices_path, 'r', encoding='utf-8') as f:
            return set(json.load(f))

    def save_processed_index(self, idx: int):
        processed = self.load_processed_indices()
        processed.add(idx)
        with open(self.processed_indices_path, 'w', encoding='utf-8') as f:
            json.dump(sorted(list(processed)), f, indent=2)

    def save_failed_index(self, idx: int):
        failed = self.load_failed_indices()
        failed.add(idx)
        with open(self.failed_indices_path, 'w', encoding='utf-8') as f:
            json.dump(sorted(list(failed)), f, indent=2)

    def select_indices(self) -> List[int]:
        all_indices = list(range(self.max_dev_examples))
        random.Random(self.seed).shuffle(all_indices)

        processed = self.load_processed_indices()
        failed = self.load_failed_indices()

        if self.retry_failed:
            skip_indices = processed
        else:
            skip_indices = processed | failed

        unprocessed = [idx for idx in all_indices if idx not in skip_indices]
        selected = unprocessed[:self.num_examples]

        print(f"\n[INDICES] Total available: {self.max_dev_examples}")
        print(f"[INDICES] Already processed: {len(processed)}")
        print(f"[INDICES] Previously failed: {len(failed)}")
        print(f"[INDICES] Selected for this run: {len(selected)}")

        return selected

    def run_framework(self, framework: str, idx: int) -> Dict[str, Any]:
        print(f"  Running {framework}...", flush=True)
        try:
            agent_func = self.FRAMEWORK_MAP[framework]
            _, result = agent_func(idx=idx, prompt_template=WEBTHINK_PROMPT_TEMPLATE, to_print=False)
            result['status'] = 'success'

            answer = result.get('answer', 'UNKNOWN')
            gt = result.get('gt_answer', 'UNKNOWN')
            em = result.get('em', 0.0)
            llm_correct = result.get('llm_correct', False)
            print(f"  > {framework}: Answer={answer[:50]}... | GT={gt[:50]}... | EM={em} | LLM={llm_correct}", flush=True)
            return result

        except Exception as e:
            print(f"  > {framework}: ERROR - {str(e)}")
            return {
                'question_idx': idx,
                'error': str(e),
                'status': 'failed',
                'framework': framework
            }

    def run_all(self):
        indices = self.select_indices()
        if not indices:
            print("\n[COMPLETE] No new indices to process!")
            return

        run_start_time = datetime.now()
        print(f"\n{'='*70}", flush=True)
        print(f"[START] Processing {len(indices)} examples", flush=True)
        print(f"{'='*70}\n", flush=True)

        successful_count = 0
        failed_count = 0

        for i, idx in enumerate(indices, 1):
            print(f"\n{'-'*70}", flush=True)
            print(f"[EXAMPLE {i}/{len(indices)}] Index: {idx}", flush=True)
            print(f"{'-'*70}", flush=True)

            framework_results = {}
            example_success = True

            for framework in self.frameworks:
                result = self.run_framework(framework, idx)
                framework_results[framework] = result
                if result.get('status') == 'failed':
                    example_success = False

            for framework, result in framework_results.items():
                self.results[framework].append(result)
                self._save_framework_results(framework)

            if example_success:
                self.save_processed_index(idx)
                successful_count += 1
                print(f"  [STATUS] Successfully processed")
            else:
                self.save_failed_index(idx)
                failed_count += 1
                print(f"  [STATUS] Failed (saved for potential retry)")

            self._save_config()

        run_end_time = datetime.now()
        self._save_run_history(run_start_time, run_end_time, len(indices), successful_count, failed_count)
        self.generate_summary()

        print(f"\n{'='*70}")
        print(f"[COMPLETE] Experiment finished")
        print(f"  Successful: {successful_count}/{len(indices)}")
        print(f"  Failed: {failed_count}/{len(indices)}")
        print(f"  Results saved to: {self.results_dir}")
        print(f"{'='*70}\n")

    def _save_framework_results(self, framework: str):
        result_path = self.results_dir / f"{framework}.json"
        with open(result_path, 'w', encoding='utf-8') as f:
            json.dump(self.results[framework], f, indent=2, ensure_ascii=False)

    def _save_config(self):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

    def _save_run_history(self, start_time, end_time, attempted, successful, failed):
        history = []
        if self.run_history_path.exists():
            with open(self.run_history_path, 'r', encoding='utf-8') as f:
                history = json.load(f)

        run_entry = {
            "run_id": len(history) + 1,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S"),
            "duration_minutes": (end_time - start_time).total_seconds() / 60,
            "num_attempted": attempted,
            "num_successful": successful,
            "num_failed": failed,
            "frameworks": self.frameworks
        }
        history.append(run_entry)

        with open(self.run_history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)

    def generate_summary(self):
        summary = {}
        for framework, results in self.results.items():
            if not results:
                continue
            valid_results = [r for r in results if r.get('status') == 'success']
            total = len(results)
            valid = len(valid_results)

            if valid > 0:
                avg_em = sum(r.get('em', 0) for r in valid_results) / valid
                avg_f1 = sum(r.get('f1', 0) for r in valid_results) / valid
                avg_llm_correct = sum(1 for r in valid_results if r.get('llm_correct', False)) / valid
                total_calls = sum(r.get('n_calls', 0) for r in valid_results)
                total_badcalls = sum(r.get('n_badcalls', 0) for r in valid_results)
                em_success_count = sum(1 for r in valid_results if r.get('em', 0) == 1.0)
                llm_success_count = sum(1 for r in valid_results if r.get('llm_correct', False))

                summary[framework] = {
                    'total_examples': total,
                    'valid_examples': valid,
                    'error_count': total - valid,
                    'accuracy_em': round(avg_em, 4),
                    'accuracy_f1': round(avg_f1, 4),
                    'accuracy_llm_judge': round(avg_llm_correct, 4),
                    'em_success_count': em_success_count,
                    'llm_success_count': llm_success_count,
                    'total_llm_calls': total_calls,
                    'total_bad_calls': total_badcalls,
                    'avg_calls_per_example': round(total_calls / valid, 2) if valid > 0 else 0
                }

        summary_path = self.results_dir / "summary.json"
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        print(f"\n{'='*70}")
        print(f"[SUMMARY] Experiment Statistics")
        print(f"{'='*70}")
        for framework, stats in summary.items():
            print(f"\n{framework.upper()}:")
            print(f"  Valid Examples: {stats['valid_examples']}/{stats['total_examples']}")
            print(f"  Accuracy (EM): {stats['accuracy_em']:.2%}")
            print(f"  Accuracy (F1): {stats['accuracy_f1']:.2%}")
            print(f"  Accuracy (LLM-Judge): {stats['accuracy_llm_judge']:.2%}")
            print(f"  Total LLM Calls: {stats['total_llm_calls']}")
            print(f"  Avg Calls/Example: {stats['avg_calls_per_example']}")


def main():
    parser = argparse.ArgumentParser(description="Run Bamboogle experiments with continuation support")
    parser.add_argument('--model', type=str, default='gemini-2.5-flash',
                       help='Model to use')
    parser.add_argument('--num-examples', type=int, default=5,
                       help='Number of examples to run')
    parser.add_argument('--frameworks', type=str, nargs='+',
                       default=['react'],
                       choices=['react', 'nexus'],
                       help='Frameworks to run')
    parser.add_argument('--seed', type=int, default=42,
                       help='Random seed for reproducibility')
    parser.add_argument('--retry-failed', action='store_true',
                       help='Retry previously failed questions')

    args = parser.parse_args()

    runner = BamboogleExperimentRunner(
        model=args.model,
        num_examples=args.num_examples,
        frameworks=args.frameworks,
        seed=args.seed,
        retry_failed=args.retry_failed
    )
    runner.run_all()


if __name__ == '__main__':
    main()
