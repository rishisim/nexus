
import unittest
from unittest.mock import MagicMock
# Adjust import for running as a module from root
from src.agents.nexus.nexus_agent import NexusAgent

class TestNexusAgent(unittest.TestCase):
    def setUp(self):
        # Mock environment and LLM
        self.mock_env = MagicMock()
        self.mock_llm = MagicMock()
        # NexusAgent now takes llm_func and env in __init__
        self.agent = NexusAgent(llm_func=self.mock_llm, env=self.mock_env)

    def test_scout_phase_parsing(self):
        # Mock LLM response for SCOUT
        self.mock_llm.side_effect = ['["Entity A", "Entity B"]']

        entities = self.agent.scout_phase("Test Question")
        self.assertEqual(entities, ["Entity A", "Entity B"])

    def test_scout_phase_fallback(self):
        # Mock LLM failure to return JSON
        self.mock_llm.side_effect = ["Invalid JSON"]

        entities = self.agent.scout_phase("Test Question")
        self.assertEqual(entities, ["Test Question"])

    def test_scout_phase_deduplication(self):
        # Mock LLM response with duplicate entities
        self.mock_llm.side_effect = ['["Entity A", "entity a", "Entity B"]']

        entities = self.agent.scout_phase("Test Question")
        self.assertEqual(entities, ["Entity A", "Entity B"])

    def test_architect_phase_bridge_detection(self):
        # Mock LLM response for ARCHITECT with a GAP
        self.mock_llm.side_effect = [
            'Status: GAP\nReasoning: Missing link.\nBridge Actions: ["Search[New Query]"]'
        ]

        # Mock Env step return
        self.mock_env.step.return_value = ("Bridge content", 0, False, {})

        passports = {"A": "Info A", "B": "Info B"}
        bridge_info, trace = self.agent.architect_phase("Question", passports, ["A", "B"])

        self.assertIn("Bridge_search_New Query", bridge_info)
        self.assertEqual(bridge_info["Bridge_search_New Query"], "Bridge content")

    def test_architect_phase_resolved(self):
        # Mock LLM response for ARCHITECT with RESOLVED
        self.mock_llm.side_effect = [
            "Status: RESOLVED\nReasoning: Link explicitly stated."
        ]

        passports = {"A": "Info A", "B": "Info B"}
        bridge_info, trace = self.agent.architect_phase("Question", passports, ["A", "B"])

        self.assertEqual(bridge_info, {})
        self.assertIn("No Bridge Actions needed", trace)

    def test_architect_phase_deduplication(self):
        # Bridge query that duplicates a Scout search should be skipped
        self.mock_llm.side_effect = [
            'Status: GAP\nReasoning: Missing link.\nBridge Actions: ["Search[A]", "Search[New Query]"]'
        ]

        self.mock_env.step.return_value = ("Bridge content", 0, False, {})

        passports = {"A": "Info A", "B": "Info B"}
        bridge_info, trace = self.agent.architect_phase("Question", passports, ["A", "B"])

        # "A" should be skipped (already searched by Scout)
        self.assertIn("Skipped (already searched by Scout)", trace)
        # "New Query" should succeed
        self.assertIn("Bridge_search_New Query", bridge_info)

    def test_architect_phase_multiple_bridges(self):
        # All bridge queries should execute (no break-on-first-success)
        self.mock_llm.side_effect = [
            'Status: GAP\nReasoning: Missing.\nBridge Actions: ["Search[Query1]", "Search[Query2]"]'
        ]

        self.mock_env.step.return_value = ("Content", 0, False, {})

        passports = {"A": "Info A"}
        bridge_info, trace = self.agent.architect_phase("Question", passports, ["A"])

        # Both bridges should be in results
        self.assertEqual(len(bridge_info), 2)

    def test_disambiguation_detection(self):
        self.assertTrue(self.agent._is_disambiguation("Foo may refer to: Bar, Baz"))
        self.assertFalse(self.agent._is_disambiguation("Foo is a well-known entity with lots of information."))

    def test_error_observation_filtering(self):
        self.assertTrue(self.agent._is_error_observation("Error executing search[X]: timeout"))
        self.assertTrue(self.agent._is_error_observation("Invalid action: foo"))
        self.assertFalse(self.agent._is_error_observation("Foo is a person born in 1990."))

    def test_fallback_answer_parse_fever(self):
        self.agent.task_type = "fever"
        lines = ["Reasoning: The claim is supported.", "The evidence shows SUPPORTS"]
        self.assertEqual(self.agent._fallback_answer_parse(lines), "SUPPORTS")

    def test_fallback_answer_parse_qa(self):
        self.agent.task_type = "hotpotqa"
        lines = ["Reasoning: Based on the evidence...", "Paris"]
        self.assertEqual(self.agent._fallback_answer_parse(lines), "Paris")

    def test_llm_call_count(self):
        # Verify exactly 3 LLM calls for a full solve
        self.mock_llm.side_effect = [
            '["Entity A"]',  # Scout
            'Status: RESOLVED\nReasoning: Done.',  # Architect
            'Reasoning: Clear.\nAnswer: SUPPORTS',  # Adjudicator
        ]
        self.mock_env.step.return_value = ("Page content about entity A", 0, False, {})

        self.agent.solve("Test claim")
        self.assertEqual(self.agent.n_calls, 3)

if __name__ == '__main__':
    unittest.main()
