"""
FEVEROUS-Specific Nexus Agent with TableLookup Support

Inherits from the base NexusAgent, which already supports Search, Lookup,
and TableLookup actions. Only needs to inject FEVEROUS-specific prompts.
"""

import logging

from src.agents.nexus.nexus_agent import NexusAgent

# Import FEVEROUS-specific prompts (relative import)
from prompts.nexus_feverous import (
    SCOUT_PROMPT_FEVEROUS,
    ARCHITECT_PROMPT_FEVEROUS,
    ADJUDICATOR_PROMPT_FEVEROUS
)

logger = logging.getLogger(__name__)


class FeverousNexusAgent(NexusAgent):
    """
    Nexus Agent specialized for FEVEROUS dataset.

    Extends base NexusAgent with FEVEROUS-specific prompts that include
    TableLookup examples. All action handling (Search, Lookup, TableLookup)
    is provided by the base class.
    """

    def __init__(self, llm_func, env):
        super().__init__(
            llm_func, env,
            task_type="feverous",
            scout_prompt=SCOUT_PROMPT_FEVEROUS,
            architect_prompt=ARCHITECT_PROMPT_FEVEROUS,
            adjudicator_prompt=ADJUDICATOR_PROMPT_FEVEROUS
        )
        self.framework = "nexus_feverous"
