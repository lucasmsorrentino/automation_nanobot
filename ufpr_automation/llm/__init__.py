"""LLM module for email classification and response drafting.

Lazy imports to avoid loading litellm at package import time
(litellm is heavy and can OOM on constrained systems).
"""


def __getattr__(name):
    if name in ("LLMClient", "GeminiClient"):
        from .client import GeminiClient, LLMClient

        return {"LLMClient": LLMClient, "GeminiClient": GeminiClient}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LLMClient", "GeminiClient"]
