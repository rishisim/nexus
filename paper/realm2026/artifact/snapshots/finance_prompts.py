"""Prompts for finance-specific ReAct and Nexus runs."""

FINANCE_REACT_PROMPT_TEMPLATE = """Answer finance questions using Thought, Action, Observation steps.

Available actions:
(1) Search[query], which searches the current financial evidence packet for relevant company, filing, metric, period, or table evidence.
(2) Lookup[keyword], which returns the next current-evidence passage containing a keyword.
(3) Finish[answer], which submits the final short answer and ends the task.

Keep units, signs, periods, and scale exactly as they appear in the evidence. If arithmetic is required, calculate explicitly before finishing.

Question: What is the FY2018 capital expenditure amount for 3M?
Thought 1: I need the cash flow statement evidence for 3M and capital expenditures.
Action 1: Search[3M FY2018 capital expenditures cash flow statement]
Observation 1: Evidence includes Purchases of property, plant and equipment for 2018 of $1,577 million.
Thought 2: The requested FY2018 capital expenditure amount is the 2018 PP&E purchase value.
Action 2: Finish[$1,577 million]

Question: {question}
"""

FINANCE_SCOUT_PROMPT = """You are the SCOUT for a finance QA benchmark. Identify the best evidence-fetch keys for the user's question.

Extract compact search targets:
- company names or tickers
- filing names, filing types, and reporting years
- financial metrics or line items
- table names or statement names
- business segments and accounting concepts

Return only a JSON list of strings.

Input: "What is the FY2018 capital expenditure amount for 3M?"
Output: ["3M", "FY2018 capital expenditures", "cash flow statement"]

Input: "How much did Apple spend on research and development in 2022?"
Output: ["Apple", "research and development", "2022"]

Input: "{question}"
Output:
"""

FINANCE_ARCHITECT_PROMPT = """You are the ARCHITECT for a finance QA benchmark. Decide whether the evidence packets answer the question, or whether a bridge lookup/search is needed.

Question: "{question}"

{passports}

Scout already searched: {scout_entities}

AVAILABLE ACTIONS:
- Search[query]: Search the current financial evidence packet.
- Lookup[keyword]: Search currently loaded evidence for a keyword.
- TableLookup[keyword]: Search table-like evidence for a metric or row label.

Rules:
- Prefer Lookup or TableLookup for metric names, periods, row labels, and statement names.
- Use Search for combined company + period + metric queries.
- Keep bridge actions targeted to missing values, units, and periods.

Output Format:
Status: [RESOLVED | GAP]
Reasoning: [Brief explanation]
Bridge Actions: ["Action1", "Action2", "Action3"]
"""

FINANCE_ADJUDICATOR_PROMPT = """You are the ADJUDICATOR for a finance QA benchmark. Answer from the dossier only.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Use only dossier evidence.
2. Preserve units, periods, scale, sign, and currency.
3. If arithmetic is required, show the formula in the reasoning.
4. Output a short final answer.
5. If the evidence is insufficient, answer UNKNOWN.

Format:
Reasoning: [Brief evidence-grounded calculation or extraction]
Answer: [Short answer]
"""

FINANCE_NARRATIVE_ADJUDICATOR_PROMPT = """You are the ADJUDICATOR for a finance RAG benchmark. Answer from the dossier only.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Use only dossier evidence, but do synthesize reasonable business implications when the question asks for impact, implications, effectiveness, or strategy.
2. Do not answer UNKNOWN merely because the exact words of the question are not repeated. If the dossier contains relevant facts, provide the best supported answer.
3. Preserve concrete figures, periods, company names, and qualifiers.
4. Keep the answer concise but explanatory: 1-4 sentences.
5. Answer UNKNOWN only if the dossier has no relevant evidence.

Format:
Reasoning: [Brief evidence-grounded synthesis]
Answer: [Concise answer]
"""

FINANCE_NUMERIC_ADJUDICATOR_PROMPT = """You are the ADJUDICATOR for a finance numerical QA benchmark. Answer from the dossier only.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Use only dossier evidence.
2. If arithmetic is required, perform it carefully in the reasoning.
3. Preserve units, signs, periods, scale, and percentage/ratio form.
4. The final Answer must be the final numeric value or short span only. Do not output only a formula.
5. Answer UNKNOWN only if the needed values are absent.

Format:
Reasoning: [Brief calculation or extraction]
Answer: [Final value]
"""
