# Related-work matrix for ICAIF 2026

This internal matrix records the verified sources behind the compact related-work section. Publication metadata was checked against the primary paper landing page (ACL Anthology, PMLR, OpenReview, or arXiv) and, for ICAIF papers, against the official conference program/accepted-paper page and ACM DOI metadata. The withdrawn **FinAgent-RAG** preprint is intentionally excluded as evidence.

## Financial QA datasets and systems

| Work | Verified record | Setting / evidence | Main contribution | Evaluation emphasis | Relationship to this paper |
| --- | --- | --- | --- | --- | --- |
| FinQA | Chen et al., EMNLP 2021, DOI `10.18653/v1/2021.emnlp-main.300` | Financial-report text and tables; gold programs | Expert-authored numerical QA with executable reasoning programs | Program and execution accuracy | Primary objective dataset; gold programs must never be model-visible |
| TAT-QA | Zhu et al., ACL-IJCNLP 2021, DOI `10.18653/v1/2021.acl-long.254` | Hybrid tables and text | Joint extraction and symbolic numerical reasoning over both modalities | Exact match/F1 plus scale handling | Primary objective dataset; gold derivation, answer type, and scale must remain hidden |
| ConvFinQA | Chen et al., EMNLP 2022, DOI `10.18653/v1/2022.emnlp-main.421` | Multi-turn financial conversations grounded in report evidence | Long-range chains of numerical reasoning across dialogue turns | Execution/program accuracy | Primary objective dataset; split by dialogue, not individual turn, to prevent overlap |
| FinanceBench | Islam et al., arXiv:2311.11944 | Open-book QA over filings; 10,231 QA/evidence triples, with a public 150-case evaluation sample | Enterprise-oriented financial QA benchmark comparing retrieval and long-context configurations | Human review in the paper | Secondary stress test here because strict scoring underserves narrative answers and no human annotation is planned |
| FinDER | Choi et al., ICAIF 2025, DOI `10.1145/3768292.3770361`; arXiv:2504.15800 | 5,703 expert query--evidence--answer triples; terse and ambiguous professional queries | Finance-specific RAG dataset designed to make evidence retrieval nontrivial | Retrieval and generation metrics | Secondary semantic stress test; controlled evidence means this paper does not claim end-to-end RAG gains |
| FinQAPT | Singh et al., ICAIF 2024, DOI `10.1145/3677052.3698682` | End-to-end report identification, context extraction, and reader pipeline on FinQA | Clustering-based negative sampling and dynamic N-shot prompting; exposes pipeline-level retrieval bottlenecks | Module and end-to-end accuracy | Closest fixed financial QA pipeline; differs because our contribution is selective orchestration under matched evidence |

## Agentic finance and evaluation

| Work | Verified record | Agentic mechanism | What it evaluates | Cost treatment | Distinction / lesson for this paper |
| --- | --- | --- | --- | --- | --- |
| ReAct | Yao et al., ICLR 2023, OpenReview `WE_vluYUL-X` | Interleaves reasoning traces and environment actions | QA and interactive decision tasks | Steps are visible, but cost is not the central objective | Iterative baseline; cap model steps and measure every model/tool call |
| Multi-Agent Reflection for Financial QA | Fatemi and Hu, ICAIF 2024, DOI `10.1145/3677052.3698686` | Generator plus one or multiple specialized critic agents | Financial numerical QA | Motivates cost-effectiveness but primarily reports accuracy | Closest agentic financial QA predecessor; our question is when critique/iteration is worth paying for |
| FinAgentBench | Choi et al., ICAIF 2025, DOI `10.1145/3768292.3770362`; arXiv:2508.14052 | Two-stage agentic retrieval: document-type selection then passage selection | Retrieval over SEC filings and earnings transcripts | Not primarily an answer-generation cost study | Establishes ICAIF interest in agentic retrieval; outside our controlled-evidence primary claim |
| FinResearchBench | Sun et al., ICAIF 2025, DOI `10.1145/3768292.3770364`; arXiv:2507.16248 | Logic-tree Agent-as-a-Judge | 70 long-form financial research questions across seven task types | Focuses judge structure, not Pareto-efficient QA | Supports structured evaluation but is too open-ended to replace native numerical scorers |
| Reasoning or Overthinking | Vamvourellis and Mehta, ICAIF 2025, DOI `10.1145/3768292.3770341` | Compares reasoning behavior on financial sentiment analysis | Financial sentiment, not document QA | Tests whether additional reasoning is useful | Finance-specific evidence that reasoning depth should be justified empirically |
| Do NOT Think That Much | Chen et al., arXiv:2412.21187 | Studies and mitigates excessive test-time reasoning | General math and science reasoning | Introduces outcome- and process-oriented efficiency views | General motivation for allocating iterative computation selectively |

## Selective inference, routing, and efficiency

| Work | Verified record | Decision unit | Objective / metrics | Distinction / use in this paper |
| --- | --- | --- | --- | --- |
| SelectiveNet | Geifman and El-Yaniv, ICML 2019, PMLR 97:2151--2159 | Predict or reject | Selective risk versus coverage | Conceptual foundation for escalating only covered/uncertain cases; our action is routing rather than abstention |
| FrugalGPT | Chen, Zaharia, and Zou, TMLR 2024, OpenReview `cSimKw5p6R` | Cascade among paid LLM APIs | Quality versus dollar cost | Establishes learned cost-sensitive cascades; our alternatives are reasoning workflows with a fixed backbone |
| RouteLLM | Ong et al., ICLR 2025, OpenReview `8sSqNntaMr`; arXiv:2406.18665 | Route between strong and weak models | Preference quality versus serving cost | Closest learned-routing method; ours routes pre-generation between static and iterative orchestration under the same model/evidence |
| Efficient Agents | Wang et al., arXiv:2508.02694 (authors mark it “work in progress”) | Agent architecture and test-time scaling | Effectiveness, operational cost, and cost-of-pass | Use only as recent motivation; do not overstate its maturity |
| Cost-of-Pass | Erol, El, Suzgun, Yuksekgonul, and Zou, arXiv:2504.13359 | Model/evaluation economics | Expected cost to obtain a passing result | Supports reporting economic efficiency alongside accuracy; raw “calls” alone is insufficient |
| RAGAs | Es et al., EACL 2024 Demo, DOI `10.18653/v1/2024.eacl-demo.16` | Reference-free RAG evaluator | Context relevance, faithfulness, and answer quality | Does not validate judge reliability for this exact finance setting | Use for blinded secondary sensitivity analysis only, never in the primary objective macro-average |

## Novelty boundary to preserve in the manuscript

1. **Not a new finance benchmark.** The paper uses established datasets and contributes a leakage-safe, paired protocol for comparing reasoning workflows.
2. **Not end-to-end retrieval.** The primary question is orchestration under controlled evidence. FinDER and FinanceBench are secondary semantic stress tests.
3. **Not simply another multi-agent system.** Deterministic Scout/Architect stages are workflow components; only the iterative branch is agentic in the ReAct sense.
4. **Not generic model routing.** The selector chooses between one-call deterministic-first adjudication and iterative action/reasoning while holding the backbone model, evidence, tools, and budget policy fixed.
5. **Main empirical contribution.** Establish whether this within-model routing traces a better accuracy--cost frontier than always-static or always-agentic execution, with native scoring on FinQA/TAT-QA/ConvFinQA and full token/dollar/latency instrumentation.

## Citation hygiene notes

- Prefer the ACM proceedings DOI for the 2024--2025 ICAIF papers; retain arXiv IDs only where useful for public access or version history.
- FinanceBench is cited as an arXiv paper because no peer-reviewed venue was verified.
- The FinDER arXiv page notes an ICLR 2025 workshop version, but the bibliography uses its later ICAIF 2025 proceedings record.
- FinAgentBench changed scale across preprint versions; avoid quoting its sample count in the related-work paragraph unless the exact evaluated release is pinned.
- Efficient Agents is explicitly marked “work in progress” by its authors; it should not carry a central novelty or validity claim.
- Do not cite or summarize results from the withdrawn FinAgent-RAG preprint.
