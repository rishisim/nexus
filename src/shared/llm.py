"""
Shared LLM module for Nexus experiments.

Supports two backends:
  - "openrouter" (default): Uses OpenRouter API (OpenAI-compatible) for higher rate limits
  - "gemini": Uses Google Generative AI (original backend)

Usage:
    from src.shared.llm import llm, llm_judge_answer

    # Uses OPENROUTER_API_KEY from .env by default
    response = llm("What is 2+2?", stop=["\\n"])

Configuration via environment variables:
    LLM_BACKEND       = "openrouter" | "gemini"   (default: "openrouter")
    LLM_MODEL          = model name               (default: auto per backend)
    OPENROUTER_API_KEY = your key                  (for openrouter backend)
    GEMINI_API_KEY     = your key                  (for gemini backend)
"""

import os
import time
import json
import requests as req
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
LLM_BACKEND = os.getenv("LLM_BACKEND", "openrouter")
LLM_MODEL = os.getenv("LLM_MODEL", None)
LLM_DELAY = float(os.getenv("LLM_DELAY", "0.1"))  # seconds between calls

# Default models per backend
_DEFAULT_MODELS = {
    "openrouter": "google/gemini-2.5-flash",
    "gemini": "gemini-2.5-flash",
}

def _get_model():
    if LLM_MODEL:
        return LLM_MODEL
    return _DEFAULT_MODELS.get(LLM_BACKEND, "google/gemini-2.5-flash")


# --- OpenRouter Backend ---
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

def _call_openrouter(prompt: str, stop: List[str], temperature: float,
                     max_tokens: int) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY not set in environment")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    body = {
        "model": _get_model(),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "top_p": 1.0,
    }
    if stop:
        body["stop"] = stop

    resp = req.post(_OPENROUTER_URL, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    data = resp.json()

    # Extract text from OpenAI-compatible response
    choices = data.get("choices", [])
    if choices:
        return choices[0].get("message", {}).get("content", "").strip()
    return ""


# --- Gemini Backend ---
_gemini_client = None

def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client()
    return _gemini_client

def _call_gemini(prompt: str, stop: List[str], temperature: float,
                 max_tokens: int) -> str:
    from google.genai import types
    client = _get_gemini_client()
    response = client.models.generate_content(
        model=_get_model(),
        contents=prompt,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            stop_sequences=stop,
            temperature=temperature,
            max_output_tokens=max_tokens,
            top_p=1.0
        )
    )
    if response and response.text:
        return response.text
    return ""


# --- Public API ---

def llm(prompt: str, stop: List[str] = ["\n"], temperature: Optional[float] = None,
        num_traces: int = 1, max_tokens: int = 512) -> str:
    """
    Call the language model. Drop-in replacement for all per-agent llm() functions.

    Args:
        prompt: Input prompt string
        stop: Stop sequences
        temperature: Override temperature (None = 0.0 for single trace, 0.7 for multi)
        num_traces: Affects default temperature
        max_tokens: Maximum output tokens

    Returns:
        Response text string
    """
    time.sleep(LLM_DELAY)

    if temperature is None:
        temp = 0.0 if num_traces == 1 else 0.7
    else:
        temp = temperature

    backend_fn = _call_openrouter if LLM_BACKEND == "openrouter" else _call_gemini

    max_retries = 3
    for attempt in range(max_retries):
        try:
            result = backend_fn(prompt, stop, temp, max_tokens)
            if result:
                return result
            # Empty response — retry
            time.sleep(1)
        except Exception as e:
            print(f"[LLM] {LLM_BACKEND} call failed (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return "I need to finish now.\nFinish[Unable to proceed due to API error]"

    return "I need to finish now.\nFinish[Unable to proceed due to API error]"


def llm_judge_answer(question: str, prediction: str, ground_truth: str) -> dict:
    """
    Use LLM as a judge to evaluate semantic equivalence.
    Shared implementation so all agents use the same evaluation.
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

    is_correct = "CORRECT" in response.upper() and "INCORRECT" not in response.upper()

    explanation = response.strip()
    if "Explanation:" in response:
        parts = response.split("Label:")
        explanation = parts[0].replace("Explanation:", "").strip() if parts else response.strip()

    return {
        'llm_correct': is_correct,
        'llm_explanation': explanation
    }
