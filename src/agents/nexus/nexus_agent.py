import re
import json
import logging
from typing import List, Dict, Any, Tuple
from src.agents.nexus.nexus_prompts import (
    SCOUT_PROMPT, ARCHITECT_PROMPT,
    ADJUDICATOR_PROMPT, ADJUDICATOR_PROMPT_FEVER, ADJUDICATOR_PROMPT_QA
)

logger = logging.getLogger(__name__)

class NexusAgent:
    """
    Nexus Agent: A graph-based agent that uses 3 phases (Scout -> Architect -> Adjudicator)
    to solve multi-hop reasoning and retrieval bottleneck problems.

    Cost: Exactly 3 LLM calls per question (Scout + Architect + Adjudicator).
    """
    def __init__(self, llm_func, env, task_type="fever",
                 scout_prompt=None, architect_prompt=None, adjudicator_prompt=None):
        self.llm = llm_func
        self.env = env
        self.framework = "nexus"
        self.task_type = task_type  # "fever", "hotpotqa", "feverous", etc.
        self.n_calls = 0  # LLM call tracking

        # Allow subclasses to inject custom prompts
        self._scout_prompt = scout_prompt or SCOUT_PROMPT
        self._architect_prompt = architect_prompt or ARCHITECT_PROMPT
        self._adjudicator_prompt = adjudicator_prompt

    def _parse_similar_results(self, obs: str) -> List[str]:
        """Parse 'Could not find X. Similar: [...]' responses to extract alternatives."""
        if "Could not find" not in obs or "Similar:" not in obs:
            return []
        try:
            match = re.search(r"Similar:\s*(\[.*?\])", obs)
            if match:
                import ast
                return ast.literal_eval(match.group(1))
        except Exception:
            pass
        return []

    def _is_invalid_search(self, obs: str) -> bool:
        """Check if observation indicates a failed search."""
        return (
            "Could not find" in obs
            or "Invalid action" in obs
            or "There were no results matching the query" in obs
            or not obs.strip()
        )

    def _is_disambiguation(self, obs: str) -> bool:
        """Check if observation is a disambiguation page (shallow content)."""
        return "may refer to" in obs or (len(obs.strip()) < 50 and obs.strip())

    def _execute_action(self, action: str) -> str:
        """
        Execute an action and return the observation.
        Handles search, lookup, and tablelookup action types.
        """
        action_stripped = action.strip()
        action_lower = action_stripped.lower()

        # Normalize action format
        if action_lower.startswith("search[") and action_stripped.endswith("]"):
            query = action_stripped[7:-1]
            full_action = f"search[{query}]"
        elif action_lower.startswith("lookup[") and action_stripped.endswith("]"):
            query = action_stripped[7:-1]
            full_action = f"lookup[{query}]"
        elif action_lower.startswith("tablelookup[") and action_stripped.endswith("]"):
            query = action_stripped[12:-1]
            full_action = f"table_lookup[{query}]"
        elif action_lower.startswith("table_lookup[") and action_stripped.endswith("]"):
            query = action_stripped[13:-1]
            full_action = f"table_lookup[{query}]"
        else:
            # Default to search
            full_action = f"search[{action_stripped}]"

        try:
            obs, _, _, _ = self.env.step(full_action)
            return obs
        except Exception as e:
            return f"Error executing {full_action}: {e}"

    def _is_error_observation(self, obs: str) -> bool:
        """Check if observation is an error message that shouldn't be used as evidence."""
        return obs.startswith("Error ") or obs.startswith("Invalid action")

    def solve(self, question: str) -> Tuple[str, Dict[str, Any]]:
        """Run the 3-phase Nexus pipeline: Scout -> Architect -> Adjudicator."""

        # --- Phase 1: SCOUT ---
        clean_question = question.replace("Question: ", "").replace("Claim: ", "").strip()
        scout_entities = self.scout_phase(clean_question)
        passports = {}
        trace = f"Question: {question}\n\n[Phase 1: Scout]\n"

        for entity in scout_entities:
            if not entity.strip():
                continue

            obs = self._execute_action(f"search[{entity}]")

            # Handle disambiguation pages
            if self._is_disambiguation(obs):
                trace += f"Scout search[{entity}] -> Disambiguation, retrying with bracket form\n"
                obs = self._execute_action(f"search[[{entity}]]")

            # Handle invalid/failed searches
            if self._is_invalid_search(obs):
                similar = self._parse_similar_results(obs)
                if similar:
                    alt_entity = similar[0]
                    trace += f"Scout search[{entity}] -> Invalid, retrying with '{alt_entity}'\n"
                    obs = self._execute_action(f"search[{alt_entity}]")
                    if not self._is_invalid_search(obs) and not self._is_error_observation(obs):
                        passports[alt_entity] = obs
                        trace += f"Scout search[{alt_entity}] -> OK\n"
                    else:
                        trace += f"Scout search[{alt_entity}] -> Also failed, skipping\n"
                    continue

            # Only store valid observations as passports
            if not self._is_error_observation(obs):
                passports[entity] = obs
                trace += f"Scout search[{entity}] -> OK\n"
            else:
                trace += f"Scout search[{entity}] -> Error, skipping\n"

        # --- Phase 2: ARCHITECT ---
        architect_result, bridge_trace = self.architect_phase(
            question, passports, scout_entities
        )
        trace += f"\n[Phase 2: Architect]\n{bridge_trace}\n"

        dossier = self.compile_dossier(passports, architect_result)

        # --- Phase 3: ADJUDICATOR ---
        answer, adj_trace = self.adjudicator_phase(question, dossier)
        trace += f"\n[Phase 3: Adjudicator]\n{adj_trace}"

        return answer, {"traj": trace, "dossier": dossier}

    def scout_phase(self, question: str) -> List[str]:
        """Extract key entities from the question. (1 LLM call)"""
        prompt = self._scout_prompt.format(question=question)
        try:
            self.n_calls += 1
            llm_output = self.llm(prompt, stop=["\n\n"])
            if "[" in llm_output and "]" in llm_output:
                start = llm_output.find("[")
                end = llm_output.rfind("]") + 1
                entities = json.loads(llm_output[start:end])
                # Filter empty and deduplicate while preserving order
                seen = set()
                unique = []
                for e in entities:
                    e_clean = e.strip()
                    if e_clean and e_clean.lower() not in seen:
                        seen.add(e_clean.lower())
                        unique.append(e_clean)
                return unique
            else:
                return [question]
        except Exception:
            return [question]

    def architect_phase(self, question: str, passports: Dict[str, str],
                        scout_entities: List[str] = None) -> Tuple[Dict[str, str], str]:
        """Analyze passports for gaps and generate bridge queries. (1 LLM call)"""
        # Build labeled passport text
        passport_text = ""
        entity_labels = list("ABCDEFGHIJ")  # Supports up to 10 entities
        for i, (entity, content) in enumerate(passports.items()):
            label = entity_labels[i] if i < len(entity_labels) else str(i)
            passport_text += f"[Passport {label}: {entity}]:\n{content}\n\n"

        # Build scout entities string for deduplication hint
        scout_str = ", ".join(scout_entities) if scout_entities else "unknown"

        prompt = self._architect_prompt.format(
            question=question,
            passports=passport_text,
            scout_entities=scout_str
        )
        self.n_calls += 1
        llm_output = self.llm(prompt, stop=[])

        trace_log = f"Architect Thought:\n{llm_output}\n"
        bridge_info = {}

        # Build set of already-searched entities for deduplication
        searched = set()
        if scout_entities:
            searched = {e.lower().strip() for e in scout_entities}

        # Parse Bridge Actions
        actions_match = re.search(r"Bridge Actions:\s*(\[.*\])", llm_output, re.DOTALL | re.IGNORECASE)

        if actions_match:
            actions = self._parse_bridge_actions(actions_match.group(1), llm_output)
            trace_log += f"Generated Bridge Candidates: {actions}\n"

            success = False
            for i, action_raw in enumerate(actions):
                if not action_raw:
                    continue

                # Extract action type and query
                action_type, query = self._extract_action_and_query(action_raw)

                if not query:
                    continue

                # Deduplication: skip if this is the same as a Scout search
                if action_type == "search" and query.lower().strip() in searched:
                    trace_log += f"Bridge Attempt {i+1} (search[{query}]) -> Skipped (already searched by Scout)\n"
                    continue

                # Execute the bridge action
                full_command = f"{action_type}[{query}]"
                obs = self._execute_action(full_command)

                if not self._is_invalid_search(obs) and not self._is_error_observation(obs):
                    bridge_info[f"Bridge_{action_type}_{query}"] = obs
                    trace_log += f"Bridge Attempt {i+1} ({full_command}) -> Success\n"
                    success = True
                    # NO break — continue to execute remaining bridge actions
                else:
                    # Try similar result (one retry, search only)
                    if action_type == "search":
                        similar = self._parse_similar_results(obs)
                        if similar:
                            alt_query = similar[0]
                            trace_log += f"Bridge Attempt {i+1} ({full_command}) -> Invalid, retrying with '{alt_query}'\n"
                            alt_obs = self._execute_action(f"search[{alt_query}]")

                            if not self._is_invalid_search(alt_obs) and not self._is_error_observation(alt_obs):
                                bridge_info[f"Bridge_search_{alt_query}"] = alt_obs
                                trace_log += f"Bridge Retry (search[{alt_query}]) -> Success\n"
                                success = True
                            else:
                                trace_log += f"Bridge Retry (search[{alt_query}]) -> Also failed\n"
                        else:
                            trace_log += f"Bridge Attempt {i+1} ({full_command}) -> Failed (No results)\n"
                    else:
                        trace_log += f"Bridge Attempt {i+1} ({full_command}) -> Failed\n"

            if not success:
                trace_log += "All Bridge queries failed.\n"
        else:
            trace_log += "No Bridge Actions needed (Status: RESOLVED or failed parsing).\n"

        return bridge_info, trace_log

    def _parse_bridge_actions(self, actions_str: str, full_output: str) -> List[str]:
        """Parse bridge actions list from LLM output."""
        try:
            import ast
            return ast.literal_eval(actions_str)
        except Exception:
            # Fallback: extract Search/Lookup/TableLookup patterns from the full output
            matches = re.findall(
                r"(Search|Lookup|Table_?Lookup)\s*[\(\[]\s*[\"']?(.*?)[\"']?\s*[\)\]]",
                full_output, re.IGNORECASE
            )
            actions = []
            for action_type, query in matches:
                if not query.strip():
                    continue
                clean_type = action_type.lower().replace('_', '')
                if clean_type == "tablelookup":
                    actions.append(f"TableLookup[{query}]")
                elif clean_type == "lookup":
                    actions.append(f"Lookup[{query}]")
                else:
                    actions.append(f"Search[{query}]")
            return actions

    def _extract_action_and_query(self, action_raw: str) -> Tuple[str, str]:
        """Extract action type and query from a raw action string like 'Search(query)', 'Lookup[keyword]', or 'TableLookup[query]'."""
        match = re.search(
            r"(Search|Lookup|Table_?Lookup)[\(\[]\s*[\"']?(.*?)[\"']?\s*[\)\]]",
            action_raw, re.IGNORECASE
        )
        if match:
            raw_type = match.group(1).lower().replace('_', '')
            query = match.group(2).strip()
            if raw_type == "tablelookup":
                return "tablelookup", query
            elif raw_type == "lookup":
                return "lookup", query
            else:
                return "search", query
        # Assume raw string is a search query
        return "search", action_raw.strip()

    def adjudicator_phase(self, question: str, dossier: str) -> Tuple[str, str]:
        """Synthesize evidence and produce final answer. (1 LLM call)"""
        # Use injected prompt if provided, else task-specific defaults
        if self._adjudicator_prompt:
            prompt = self._adjudicator_prompt.format(question=question, dossier=dossier)
        elif self.task_type == "fever" or self.task_type == "feverous":
            prompt = ADJUDICATOR_PROMPT_FEVER.format(question=question, dossier=dossier)
        elif self.task_type in ("hotpotqa", "musique"):
            prompt = ADJUDICATOR_PROMPT_QA.format(question=question, dossier=dossier)
        else:
            prompt = ADJUDICATOR_PROMPT.format(question=question, dossier=dossier)

        self.n_calls += 1
        llm_output = self.llm(prompt, stop=[])

        # Extract Answer — strict format first
        match = re.search(r"^Answer:\s*(.+)$", llm_output, re.MULTILINE | re.IGNORECASE)
        if match:
            answer = match.group(1).strip()
        else:
            # Fallback parsing
            lines = llm_output.strip().split('\n')
            answer = self._fallback_answer_parse(lines)

        return answer, llm_output

    def _fallback_answer_parse(self, lines: List[str]) -> str:
        """Parse answer from LLM output when strict 'Answer: ...' format fails."""
        if self.task_type in ("fever", "feverous"):
            valid_labels = ["SUPPORTS", "REFUTES", "NOT ENOUGH INFO"]
            for line in reversed(lines):
                clean_line = line.upper().strip()
                for label in valid_labels:
                    if label in clean_line:
                        return label
            return "NOT ENOUGH INFO"
        else:
            # For QA: return the last non-empty line
            for line in reversed(lines):
                stripped = line.strip()
                if stripped and not stripped.lower().startswith("reasoning"):
                    return stripped
            return "null"

    def compile_dossier(self, passports: Dict[str, str], bridge_info: Dict[str, str]) -> str:
        """Compile all evidence into a structured dossier for the Adjudicator."""
        dossier = ""
        for ent, text in passports.items():
            dossier += f"--- Information on {ent} ---\n{text}\n\n"
        for ent, text in bridge_info.items():
            dossier += f"--- Bridge Info: {ent} ---\n{text}\n\n"
        return dossier
