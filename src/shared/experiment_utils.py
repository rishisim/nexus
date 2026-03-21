"""
Shared utilities for experiment runners across all datasets.

Consolidates duplicated functions: step(), append_to_json(), EnvWrapper.
"""

import json
import os
import time

import requests

# --- Constants ---
MAX_RETRY_ATTEMPTS = 10
RETRY_DELAY_SECONDS = 2
MAX_STEPS_PER_TRACE = 7


def step(current_env, action):
    """
    Execute a step in the environment with retry logic for timeouts.

    Args:
        current_env: The environment (WikiEnv, SciFact, etc.)
        action: Action string to execute

    Returns:
        Tuple of (observation, reward, done, info)
    """
    attempts = 0
    while attempts < MAX_RETRY_ATTEMPTS:
        try:
            return current_env.step(action)
        except requests.exceptions.Timeout:
            print(f"[WARNING] Timeout during env.step attempt {attempts+1} for action: {action}")
            attempts += 1
            time.sleep(RETRY_DELAY_SECONDS)

    print(f"[ERROR] Failed to execute step after {MAX_RETRY_ATTEMPTS} attempts due to timeout for action: {action}")
    return "Timeout after 10 attempts", 0, False, {"error": "API Timeout"}


def append_to_json(data, filename):
    """Append data to a JSON file that stores a list of JSON objects."""
    if os.path.exists(filename):
        with open(filename, 'r+') as f:
            try:
                file_data = json.load(f)
            except json.JSONDecodeError:
                file_data = []

            if isinstance(file_data, list):
                file_data.append(data)
            else:
                file_data = [data]

            f.seek(0)
            json.dump(file_data, f, indent=4)
            f.truncate()
    else:
        with open(filename, 'w') as f:
            json.dump([data], f, indent=4)


class EnvWrapper:
    """Wraps an environment to use the robust step function with retry logic."""
    def __init__(self, env):
        self.env = env

    def step(self, action):
        return step(self.env, action)

    def reset(self, idx=None):
        return self.env.reset(idx=idx)
