"""Frozen prompts for the REALM 2026 context-harmonized replication."""

ANSWER_CONTRACT = (
    'Return exactly one JSON object. To answer, use '
    '{"thought":"brief reasoning","action":"Finish","answer":"short answer"}. '
    'If the evidence is insufficient, set answer to "UNKNOWN". Do not use markdown.'
)

STATIC_PROMPT = """You are the one-call Static financial-QA system.
Use only the evidence shown below. Preserve the requested period, sign, unit,
scale, and currency. Calculate explicitly in the private `thought` field when
needed.

Question: {question}

Evidence observed within the shared budget:
{evidence}

{answer_contract}
"""

REACT_PROMPT = """You are the bounded iterative ReAct financial-QA system.
Use only the controlled evidence packet through the actions below:
- Search: {{"thought":"brief reasoning","action":"Search","argument":"query"}}
- Lookup: {{"thought":"brief reasoning","action":"Lookup","argument":"keyword"}}
- Finish: {{"thought":"brief reasoning","action":"Finish","answer":"short answer"}}

Preserve the requested period, sign, unit, scale, and currency. You have at
most {max_steps} model steps and {max_retrieval_operations} evidence actions.
Malformed JSON, an invalid action, or a missing required field immediately
submits UNKNOWN without a retry.

Question: {question}

Evidence observed within the shared budget:
{evidence}

Recent interaction log:
{history}

{answer_contract}
"""
