# ICAIF 2026 Integration Log

Started: 2026-07-09  
Branch: `icaif26/selective-finance-qa`  
Base commit: `145f0f69ec6d5c6a2a8c7ec4ab598ab21386a663`  
Protocol target: `finance_icaif26_v2`  
Freeze state: **OPEN — final evaluation prohibited**

## Environment Snapshot

- Python: 3.10.20 (`nexus_env`)
- datasets: 4.8.3
- scikit-learn: 1.0.2
- scipy: 1.7.3
- numpy: 1.22.4
- requests: 2.32.5
- google-genai: 1.56.0
- matplotlib: 3.7.5 (installed after the Wave 0 snapshot)
- pytest: 9.1.1 (installed after the Wave 0 snapshot)
- LaTeX: bundled Tectonic 0.16.9 smoke test passed
- TeX Live: 2026 at `/Library/TeX/texbin`, smoke test passed
- Configured provider credentials: Gemini and OpenRouter (presence only; values not recorded)

## Locked Study Decisions

- Controlled-evidence reasoning study; no end-to-end RAG claim.
- Existing 50 examples per dataset are development-only.
- Final target: 900 untouched examples.
- Primary model: `google/gemini-2.5-flash`, thinking disabled.
- Replication model: `openai/gpt-5.6-luna`, `reasoning_effort=none`.
- Primary objective datasets: FinQA, TAT-QA, ConvFinQA.
- FinanceBench and FinDER semantic evaluations are secondary.
- API budget ceiling: USD 150.
- OpenRouter credit available at Wave 0 check: USD 71.97; use USD 70 as
  the live hard ceiling unless replenished, with a 20% retry reserve.

## Agent Ownership

| Agent | Ownership | Status |
| --- | --- | --- |
| validity | finance evidence adapters and leakage tests | complete; integration tests passed |
| telemetry | shared LLM metadata/model binding and tests | complete; integration tests passed |
| scoring | finance scoring/statistics modules and tests | complete; integration tests passed |
| methods | baselines/selective router and tests | complete; development runs passed |
| protocol_runner | protocol v2, manifests, runner and tests | complete; final gate remains closed |
| literature | bibliography and related-work section/matrix | complete; citation audit passed |
| manuscript | anonymous manuscript sections and hostile review | complete; development-pivot revision in progress |

## Integration Gates

- [x] Development/final manifests are byte-stable and disjoint.
- [x] ConvFinQA dialogue IDs are disjoint across development/final.
- [x] No target-derived adapter fields are rendered.
- [x] Explicit model ID reaches mocked and live provider requests.
- [x] Usage, cost, latency, and retry telemetry pass fixtures.
- [x] Native scorer fixtures pass.
- [x] All five systems share evidence/tool budgets.
- [x] Selective router uses pre-answer, non-gold features only.
- [x] Two-example-per-dataset framework smoke test passes.
- [x] Gemini and GPT-5.6 Luna binding smoke tests pass.
- [x] Anonymous ACM manuscript compiles and remains within eight pages (5 pages; no overfull boxes or ACM metadata/accessibility warnings).

Final evaluation may begin only after every applicable gate above is checked and
the frozen protocol hashes are recorded below.

## Frozen Artifact Hashes

- Development-selected router:
  `sha256:6d3eb8c45db852853e3b6354304e1ad69c6776a0ac4831263f2accc6ae3234b6`
- Remaining protocol hashes intentionally unset. The protocol remains open and
  the final runner therefore refuses all final-partition runs.

## Test and Run History

- Leakage and cached-adapter smoke tests: 9 passed.
- Telemetry/model-binding fixtures: 10 passed.
- Full finance integration suite: 96 passed.
- Actual manifest regeneration against cached adapters is byte-identical; final
  counts are 100/200/200/200/200 (900 total) with zero ID overlap and zero
  ConvFinQA dialogue overlap.
- Live model-binding calls succeeded for Gemini 2.5 Flash and GPT-5.6 Luna.
- Five-system, two-example-per-dataset development smoke: 50/50 success, 100%
  telemetry completeness, USD 0.044 total measured cost.
- Full repaired development sweep: 250 examples x Direct, CoT/PoT, ReAct,
  Static Nexus, and Selective Nexus (1,250 paired rows); zero saved
  infrastructure/model failures; USD 1.340497 measured total cost.
- Primary development macro / cost per example: Direct 0.4138 / USD 0.000343;
  CoT/PoT 0.4323 / USD 0.000819; Static Nexus 0.4304 / USD 0.001010;
  ReAct 0.2993 / USD 0.001479; Selective 0.3675 / USD 0.001322.
- Router fit used 200 objective-labeled examples; FinDER was excluded because
  semantic judgments are secondary and not human-validated. Only 10 examples
  were ReAct-only correct, triggering the prespecified rule fallback. The rule
  escalated 70%; the fresh selective rerun achieved 0.295 exact accuracy versus
  0.395 always-static (the offline saved-branch estimate was 0.280).
- **Conditional stop fired:** Selective is dominated and Static Nexus is also
  slightly dominated by CoT/PoT. Per the locked plan, the 900 final examples
  remain untouched and this version is workshop/later-study material, not an
  ICAIF 2026 main-track claim.
- Current ACM build: successful, 5 pages; references resolved; every page
  rendered and visually checked after the development pivot; no overfull boxes,
  missing descriptions, placeholder text, or ACM metadata warnings. Only one
  underfull page notice and the standard column-balance notice remain.
- Native-scorer audit cross-checked the implemented FinQA five-decimal/
  percentage behavior and TAT-QA answer/scale plus DROP-style EM/F1 behavior
  against the original benchmark repositories.
