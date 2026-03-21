"""
2WikiMultiHop Environment and Utilities

This module provides environment and utility functions for running agents
on the 2WikiMultiHop dataset.
"""

import os
import re
import time
import json
import sys
from typing import List, Dict, Any, Tuple, Optional
from datasets import load_dataset
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# --- LLM Configuration ---
# Uses shared LLM module (supports OpenRouter + Gemini backends)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../shared')))
from llm import llm


class WikiMultiHopEnv:
    """
    Environment for 2WikiMultiHop dataset.
    
    This environment provides context from the dataset for each question,
    simulating Wikipedia searches using the provided context paragraphs.
    """
    
    def __init__(self, split: str = "train"):
        """
        Initialize the environment.
        
        Args:
            split: Dataset split to use ("train", "validation", or "test")
        """
        print(f"Loading 2WikiMultiHop dataset ({split} split)...")
        self.dataset = load_dataset("framolfese/2WikiMultihopQA", split=split)
        self.split = split
        self.current_idx = None
        self.current_item = None
        self.context_map = {}  # Maps entity titles to their sentences
        
    def reset(self, idx: int = None) -> str:
        """
        Reset the environment to a specific question.
        
        Args:
            idx: Index of the question in the dataset
            
        Returns:
            The question string
        """
        if idx is None:
            idx = 0
        
        self.current_idx = idx
        self.current_item = self.dataset[idx]
        
        # Build context map from the provided context
        self.context_map = {}
        titles = self.current_item['context']['title']
        sentences_list = self.current_item['context']['sentences']
        
        for title, sentences in zip(titles, sentences_list):
            # Join sentences into a paragraph
            self.context_map[title.lower()] = " ".join(sentences)
        
        return self.current_item['question']
    
    def step(self, action: str) -> Tuple[str, float, bool, Dict[str, Any]]:
        """
        Execute an action in the environment.
        
        Supported actions:
        - search[entity]: Look up entity in context
        - lookup[keyword]: Find sentences with keyword (simplified)
        - finish[answer]: Complete with answer
        
        Args:
            action: Action string (e.g., "search[Stuart Rosenberg]")
            
        Returns:
            Tuple of (observation, reward, done, info)
        """
        if self.current_item is None:
            return "Error: Environment not reset", 0.0, True, {}
        
        # Parse action
        action = action.strip()
        action_match = re.match(r'(\w+)\[(.+)\]$', action, re.IGNORECASE)
        
        if not action_match:
            return f"Invalid action format: {action}", 0.0, False, {}
        
        action_type = action_match.group(1).lower()
        action_arg = action_match.group(2)
        
        if action_type == "search":
            return self._search(action_arg)
        elif action_type == "lookup":
            return self._lookup(action_arg)
        elif action_type == "finish":
            return self._finish(action_arg)
        else:
            return f"Unknown action type: {action_type}", 0.0, False, {}
    
    def _search(self, entity: str) -> Tuple[str, float, bool, Dict[str, Any]]:
        """Search for an entity in the context."""
        entity_lower = entity.lower().strip()
        
        # Try exact match first
        if entity_lower in self.context_map:
            return self.context_map[entity_lower], 0.0, False, {}
        
        # Try partial match
        for title, content in self.context_map.items():
            if entity_lower in title or title in entity_lower:
                return content, 0.0, False, {}
        
        # Return similar entities if not found
        similar = [t for t in self.context_map.keys() if any(
            word in t for word in entity_lower.split()
        )][:5]
        
        if similar:
            return f"Could not find '{entity}'. Similar: {similar}", 0.0, False, {}
        else:
            return f"Could not find '{entity}'. No similar entities found.", 0.0, False, {}
    
    def _lookup(self, keyword: str) -> Tuple[str, float, bool, Dict[str, Any]]:
        """Lookup a keyword in all contexts."""
        keyword_lower = keyword.lower()
        
        for title, content in self.context_map.items():
            if keyword_lower in content.lower():
                # Return the sentence containing the keyword
                sentences = content.split('. ')
                for sent in sentences:
                    if keyword_lower in sent.lower():
                        return sent, 0.0, False, {}
        
        return f"No results found for keyword: {keyword}", 0.0, False, {}
    
    def _finish(self, answer: str) -> Tuple[str, float, bool, Dict[str, Any]]:
        """Finish with an answer and compute reward."""
        gt_answer = self.current_item['answer'].lower().strip()
        pred_answer = answer.lower().strip()
        
        # Compute exact match
        em = 1.0 if pred_answer == gt_answer else 0.0
        
        # Compute simple F1 (token overlap)
        pred_tokens = set(pred_answer.split())
        gt_tokens = set(gt_answer.split())
        
        if len(pred_tokens) == 0 or len(gt_tokens) == 0:
            f1 = 0.0
        else:
            precision = len(pred_tokens & gt_tokens) / len(pred_tokens)
            recall = len(pred_tokens & gt_tokens) / len(gt_tokens)
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        
        info = {
            'gt_answer': self.current_item['answer'],
            'answer': answer,
            'em': em,
            'f1': f1,
            'question_type': self.current_item['type'],
            'question_id': self.current_item['id']
        }
        
        return f"Episode finished. Answer: {answer}", em, True, info
    
    def get_item(self, idx: int) -> Dict[str, Any]:
        """Get a specific item from the dataset."""
        return self.dataset[idx]
    
    def get_indices_by_type(self, task_type: str, limit: int = None) -> List[int]:
        """Get indices of questions of a specific type."""
        indices = []
        for i, item in enumerate(self.dataset):
            if item['type'] == task_type:
                indices.append(i)
                if limit and len(indices) >= limit:
                    break
        return indices


def llm_judge_answer(question: str, prediction: str, ground_truth: str) -> Dict[str, Any]:
    """
    Use LLM as a judge to evaluate semantic equivalence of answer.
    """
    prompt = f"""You are an expert evaluator for a Question Answering system.

Question: {question}
Ground Truth Answer: {ground_truth}
Predicted Answer: {prediction}

Task: Determine if the "Predicted Answer" is semantically equivalent to the "Ground Truth Answer".

Guidelines:
- Ignore minor formatting differences (punctuation, capitalization)
- Allow for synonyms or different entity aliases (e.g., "JFK" = "John F. Kennedy")
- If the prediction adds extra correct context, it is ACCEPTABLE
- If the prediction is vague or missing key information, it is INCORRECT

Output:
Explanation: [Brief reasoning]
Label: [CORRECT or INCORRECT]"""
    
    response = llm(prompt, stop=[], num_traces=1)
    
    # Parse response
    is_correct = "CORRECT" in response.upper() and "INCORRECT" not in response.upper()
    
    explanation = response.strip()
    if "Explanation:" in response:
        parts = response.split("Label:")
        explanation = parts[0].replace("Explanation:", "").strip() if parts else response.strip()
    
    return {
        'llm_correct': is_correct,
        'llm_explanation': explanation
    }
