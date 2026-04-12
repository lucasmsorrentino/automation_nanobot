"""Three-phase multi-agent pipeline for UFPR email automation.

PerceberAgent  →  PensarAgent (×N, concurrent)  →  AgirAgent
    │                       │                          │
  Playwright             Gemini API                 Playwright
  (sequential)           (parallel)                (sequential)

Imports are lazy (PEP 562 ``__getattr__``) so importing this package does
NOT pull in Playwright. Tests and code paths that don't touch the OWA
agents can run in environments where ``playwright`` is not installed.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ufpr_automation.agents.agir import AgirAgent
    from ufpr_automation.agents.pensar import PensarAgent
    from ufpr_automation.agents.perceber import PerceberAgent

__all__ = ["PerceberAgent", "PensarAgent", "AgirAgent"]


def __getattr__(name: str):
    if name == "AgirAgent":
        from ufpr_automation.agents.agir import AgirAgent

        return AgirAgent
    if name == "PensarAgent":
        from ufpr_automation.agents.pensar import PensarAgent

        return PensarAgent
    if name == "PerceberAgent":
        from ufpr_automation.agents.perceber import PerceberAgent

        return PerceberAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
