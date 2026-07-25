"""Frozen prompt templates for the ICAIF finance method comparison.

The templates deliberately accept only a question and a controlled-evidence
dossier.  Dataset targets and target-derived metadata must never be formatted
into these prompts.
"""

DIRECT_PROMPT = """Answer the financial question using only the evidence dossier.

Question: {question}

Evidence dossier:
{dossier}

Preserve the requested period, sign, unit, scale, and currency. If the evidence
is insufficient, answer UNKNOWN. Return exactly one line:
Answer: [short answer]
"""


COT_PROMPT = """Solve the financial question using only the evidence dossier.

Question: {question}

Evidence dossier:
{dossier}

Reason step by step. For numerical questions, write the operands and formula
before calculating. Preserve the requested period, sign, unit, scale, and
currency. If the evidence is insufficient, answer UNKNOWN. End with exactly:
Answer: [short answer]
"""


NEXUS_PROMPT = """You are the adjudication stage of a deterministic-first
financial QA workflow. Use only the structured evidence dossier below.

Question: {question}

Structured evidence dossier:
{dossier}

Reconcile duplicate passages and verify periods, signs, units, scale, and
currency. Show a compact formula when arithmetic is required. If the evidence
is insufficient, answer UNKNOWN. End with exactly:
Answer: [short answer]
"""


REACT_PROMPT = """Answer financial questions with Thought, Action, Observation
steps. Use only these actions:
- Search[query]: search the controlled evidence packet.
- Lookup[keyword]: inspect the currently selected evidence.
- Finish[answer]: submit the final answer.

Keep periods, signs, units, scale, and currency exact. Calculate explicitly when
needed. You have at most {max_steps} model steps.

Question: {question}
"""
