# Prompts for the Nexus Framework

# Phase 1: SCOUT (Entity Extraction)
SCOUT_PROMPT = """You are the SCOUT. Your goal is to identify the key entities in a user's question so that we can fetch their "Passports" (core summaries) in parallel.

Extract:
- People (use full names)
- Films/Books/Works (add "(film)" or "(novel)" if the name is ambiguous)
- Organizations (companies, institutions, governing bodies)
- Events (tournaments, elections, wars)
- Places (cities, countries, landmarks)

Use the most specific, commonly used name for each entity. For disambiguation-prone names, add qualifiers (e.g., "Jaws (film)" not "Jaws").

Input: "Tracey Edmonds produced Soul Food."
Output: ["Tracey Edmonds", "Soul Food (film)"]

Input: "What is the shared country of ancestry between Art Laboe and Scout Tufankjian?"
Output: ["Art Laboe", "Scout Tufankjian"]

Input: "Did the same director who directed 'Jaws' also direct 'E.T.'?"
Output: ["Jaws (film)", "E.T. the Extra-Terrestrial"]

Input: "The Zou is more commonly known as what?"
Output: ["Faurot Field"]

Input: "Who is the paternal grandfather of Rhescuporis I?"
Output: ["Rhescuporis I"]

Input: "{question}"
Output:
"""

# Phase 2: ARCHITECT (Link Analysis & Bridging)
ARCHITECT_PROMPT = """You are the ARCHITECT. Your goal is to verify if independent "Passports" (summaries) connect to form a valid answer, or if we need "Bridge Actions" to fill a gap.

Question: "{question}"

{passports}

Scout already searched: {scout_entities}

AVAILABLE ACTIONS:
- Search[entity]: Search for a NEW Wikipedia page (use for entities NOT already in passports)
- Lookup[keyword]: Search the CURRENT page for sentences containing keyword (free, no new page fetch)

Task 1: Entity Resolution (NLI Check)
Given the passports above, is the relationship defined in the question supported, refuted, or unknown?
- If the relationship is EXPLICITLY confirmed or denied in the text, Output: "Status: RESOLVED".
- If the relationship is inferred but not explicit, or if a link is missing, Output: "Status: GAP".

Task 2: Bridge Action Generation (Only if GAP)
If there is a GAP, formulate Bridge Actions to fill it.

RULES:
- Do NOT generate Search queries for entities already in the passports above.
- Prefer Lookup[keyword] when the answer might be deeper in an already-fetched page (e.g., a specific attribute like producer, birth year, spouse).
- Use Search[entity] only for NEW entities or specific attribute lists not in the passports.
- Make queries "Conceptually Orthogonal" — target the MISSING ATTRIBUTE, not the entity names.

Examples:
Question: "Did Tracey Edmonds produce Soul Food?"
Gap: Tracey's bio doesn't mention Soul Food. Soul Food's bio doesn't mention Tracey.
Good Bridge: ["Lookup[producer]", "Search[Soul Food film producers]"]

Question: "Which director is younger, Roy William Neill or Mario Bava?"
Gap: Birth years not in summaries.
Good Bridge: ["Lookup[born]", "Search[Mario Bava filmography]"]

Output Format:
Status: [RESOLVED | GAP]
Reasoning: [Brief explanation]
Bridge Actions: ["Action1", "Action2", "Action3"]
(Provide up to 3 actions, prioritized. If no bridge needed, return empty list [])
"""

# Phase 3: ADJUDICATOR (Synthesis)
ADJUDICATOR_PROMPT_FEVER = """You are the ADJUDICATOR. You have a full dossier of evidence. Your job is to give the final verdict.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Answer based ONLY on the dossier evidence.
2. Output one of: SUPPORTS, REFUTES, or NOT ENOUGH INFO.
3. If evidence strongly implies an answer through context (e.g., a "West German film" implies a German director), use that inference rather than defaulting to NOT ENOUGH INFO.
4. Only output NOT ENOUGH INFO if the dossier truly contains no relevant evidence.

Format:
Reasoning: [Step-by-step deduction from the evidence]
Answer: [SUPPORTS | REFUTES | NOT ENOUGH INFO]
"""

ADJUDICATOR_PROMPT_QA = """You are the ADJUDICATOR. You have a full dossier of evidence. Your job is to give the final answer.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Answer based on the dossier evidence.
2. Output ONLY the short answer (a name, date, place, number, yes/no, etc.).
3. Do NOT say "not enough info" — make your best guess from the available evidence.
4. If evidence strongly implies an answer through context, use that inference.

Format:
Reasoning: [Step-by-step deduction from the evidence]
Answer: [Short answer]
"""

# CREAK: Commonsense claim verification (TRUE/FALSE)
ADJUDICATOR_PROMPT_CREAK = """You are the ADJUDICATOR. You have a full dossier of evidence. Your job is to give the final verdict.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Answer based ONLY on the dossier evidence.
2. Output one of: TRUE or FALSE.
3. The claim often requires commonsense reasoning combined with factual knowledge. Consider whether the claim makes a sensible assertion about the entity.
4. If the claim makes a factually incorrect or nonsensical assertion about the entity, output FALSE.
5. If the claim makes a factually correct and sensible assertion, output TRUE.

Format:
Reasoning: [Step-by-step deduction from the evidence]
Answer: [TRUE | FALSE]
"""

# HoVer: Multi-hop claim verification (SUPPORTED/NOT_SUPPORTED)
ADJUDICATOR_PROMPT_HOVER = """You are the ADJUDICATOR. You have a full dossier of evidence. Your job is to give the final verdict.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Answer based ONLY on the dossier evidence.
2. Output one of: SUPPORTED or NOT_SUPPORTED.
3. A claim is SUPPORTED only if the dossier evidence explicitly confirms ALL parts of the claim.
4. If any part of the claim is contradicted or cannot be verified from the evidence, output NOT_SUPPORTED.

Format:
Reasoning: [Step-by-step deduction from the evidence]
Answer: [SUPPORTED | NOT_SUPPORTED]
"""

# Legacy combined prompt for backward compatibility
ADJUDICATOR_PROMPT = """You are the ADJUDICATOR. You have a full dossier of evidence. Your job is to give the final answer.

Question: "{question}"

[Dossier]:
{dossier}

Instructions:
1. Answer the question based ONLY on the dossier.
2. If the question is a verification (True/False/Claims), output SUPPORTS, REFUTES, or NOT ENOUGH INFO.
3. If the question is a QA task, output the short answer.

Format:
Reasoning: [Step-by-step deduction]
Answer: [Final Answer]
"""
