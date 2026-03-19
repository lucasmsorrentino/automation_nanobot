"""Three-phase multi-agent pipeline for UFPR email automation.

PerceberAgent  →  PensarAgent (×N, concurrent)  →  AgirAgent
    │                       │                          │
  Playwright             Gemini API                 Playwright
  (sequential)           (parallel)                (sequential)
"""

from ufpr_automation.agents.perceber import PerceberAgent
from ufpr_automation.agents.pensar import PensarAgent
from ufpr_automation.agents.agir import AgirAgent

__all__ = ["PerceberAgent", "PensarAgent", "AgirAgent"]
