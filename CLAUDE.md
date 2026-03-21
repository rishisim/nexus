# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Research project comparing multi-agent reasoning frameworks (ReAct, Reflexion, CoT-SC, Nexus, etc.) across fact-verification and multi-hop QA datasets (FEVER, HotPotQA, FEVEROUS, SciFact, MusiQue, WikiMultihop). Built on the ReAct paper's codebase, extended with multiple reasoning strategies and a unified experiment runner.

## Environment Setup

```bash
source nexus_env/bin/activate
pip install -r requirements.txt
```

Required environment variables in `.env`:
- `OPENROUTER_API_KEY` — primary LLM backend
- `GEMINI_API_KEY` — fallback backend
- `LLM_BACKEND` — "openrouter" (default) or "gemini"
- `LLM_MODEL` — override default model
- `LLM_DELAY` — seconds between LLM calls (default 0.1)

## Running Experiments

```bash
# From repo root, with venv activated
cd src/agents/fever && python run_fever_experiments.py --num-examples 10 --seed 42 --frameworks react nexus
cd src/agents/hotpotqa && python run_hotpotqa_experiments.py --num-examples 10 --seed 42
cd src/agents/scifact && python run_scifact_experiments.py --num-examples 10
```

## Running Tests

```bash
# Nexus unit tests (mock-based, no API calls)
python -m unittest src.agents.nexus.test_nexus_unit

# Integration tests (require API key)
python src/agents/fever/test_agents.py

# Quick single-example sanity check
python src/agents/fever/quick_test.py
```

## Architecture

### Agent Structure

Each dataset has its own directory under `src/agents/{task}/` containing:
- `*_agent.py` — framework-specific agent logic (react, cot_sc, reflexion, etc.)
- `*_utils.py` — task-specific utilities (LLM calls, environment setup, prompt loading)
- `nexus_wrapper.py` — Nexus framework adapter
- `run_{task}_experiments.py` — experiment orchestration
- `prompts/` — JSON prompt templates

### Shared Layer (`src/shared/`)

- **`llm.py`** — Unified LLM interface with OpenRouter/Gemini backends, retry logic, and `llm_judge_answer()` for semantic evaluation. Always use this instead of per-agent LLM functions.
- **`wikienv.py`** — Gym-compatible Wikipedia environment providing `search[query]`, `lookup[keyword]`, `finish[answer]` actions.
- **`wrappers.py`** — Dataset wrappers (`FeverWrapper`, `HotPotQAWrapper`, `FeverousWrapper`), trajectory logging (`LoggingWrapper`), and answer normalization (`normalize_answer()`, `f1_score()`).
- **`experiment_utils.py`** — Shared experiment helpers: robust `step()` with retry/timeout, `append_to_json()`, `EnvWrapper`.

### Nexus Framework (`src/agents/nexus/nexus_agent.py`)

Three-phase pipeline using exactly 3 LLM calls per question:
1. **Scout** — extracts key entities, generates initial search queries
2. **Architect** — analyzes evidence, generates bridge queries to fill gaps
3. **Adjudicator** — synthesizes all evidence into a final answer

### Environment Composition Chain

```
WikiEnv (base) → {Task}Wrapper (dataset) → LoggingWrapper (trajectory) → EnvWrapper (robust step)
```

### Agent Function Interface

All agent functions follow: `run_{framework}(idx, prompt_template, to_print) → (reward, info_dict)`

`info_dict` keys: `question_idx`, `answer`, `gt_answer`, `em`, `f1`, `reward`, `n_calls`, `traj`

### Experiment Results

```
results/{task}/seed{seed}_{model}/
├── config.json, processed_indices.json, run_history.json
├── {framework}.json    # per-framework results
└── summary.json        # aggregated metrics
```

Experiments support continuation — rerunning with the same seed resumes from checkpoint.

## Key Conventions

- Temperature: 0.0 for single-trace agents, 0.7 for multi-trace
- New agents should follow the existing wrapper pattern and use the shared `llm()` function
- Action format in prompts: `search[query]`, `lookup[keyword]`, `finish[answer]`, `table_lookup[query]`
- FEVER answers must be one of: SUPPORTS, REFUTES, NOT ENOUGH INFO
- Update `PROJECT_STATE.md` when making significant structural changes
