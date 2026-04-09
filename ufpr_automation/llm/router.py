"""Model cascading router for the UFPR email pipeline.

Routes LLM calls to the optimal model based on task type:
  - Classification (category, confidence) → cheap/local model (e.g. Ollama)
  - Drafting (response generation, Self-Refine) → capable API model (e.g. MiniMax)

Falls back automatically when the primary model is unavailable (timeout,
rate limit, connection refused — common with local Ollama).

Usage:
    from ufpr_automation.llm.router import get_model, TaskType

    model = get_model(TaskType.CLASSIFY)   # → "ollama/qwen3:8b" or fallback
    model = get_model(TaskType.DRAFT)      # → "minimax/MiniMax-M2"
    model = get_model(TaskType.CRITIQUE)   # → same as DRAFT

    # Or call directly with fallback:
    response = await cascaded_completion(TaskType.CLASSIFY, messages=msgs)
"""

from __future__ import annotations

import enum
from typing import Any

from ufpr_automation.config import settings
from ufpr_automation.utils.logging import logger


class TaskType(enum.Enum):
    """LLM task types for model routing."""

    CLASSIFY = "classify"    # Category + confidence (simpler, high volume)
    DRAFT = "draft"          # Response generation (complex, quality-critical)
    CRITIQUE = "critique"    # Self-Refine critique step
    REFINE = "refine"        # Self-Refine refinement step


# Task → model mapping: which setting to use for each task type
_TASK_MODEL_MAP: dict[TaskType, str] = {
    TaskType.CLASSIFY: "classify",
    TaskType.DRAFT: "draft",
    TaskType.CRITIQUE: "draft",
    TaskType.REFINE: "draft",
}


def is_cascading_enabled() -> bool:
    """Return True if model cascading is configured (at least one override set)."""
    return bool(settings.LLM_CLASSIFY_MODEL or settings.LLM_DRAFT_MODEL)


def get_model(task: TaskType) -> str:
    """Return the model ID for a given task type.

    Priority:
      1. Task-specific model (LLM_CLASSIFY_MODEL / LLM_DRAFT_MODEL)
      2. Default model (LLM_MODEL)
    """
    role = _TASK_MODEL_MAP[task]
    if role == "classify" and settings.LLM_CLASSIFY_MODEL:
        return settings.LLM_CLASSIFY_MODEL
    if role == "draft" and settings.LLM_DRAFT_MODEL:
        return settings.LLM_DRAFT_MODEL
    return settings.LLM_MODEL


def get_fallback_model(task: TaskType) -> str | None:
    """Return the fallback model for a given task, or None if not configured.

    Fallback chain:
      - If task-specific model is set → fallback is LLM_MODEL (the default)
      - If LLM_FALLBACK_MODEL is set → that's always the last resort
      - If using the default model already → fallback is LLM_FALLBACK_MODEL
    """
    primary = get_model(task)

    # If primary is a task-specific override, fallback to default
    if primary != settings.LLM_MODEL:
        return settings.LLM_MODEL

    # If primary is already the default, fallback to explicit fallback
    if settings.LLM_FALLBACK_MODEL:
        return settings.LLM_FALLBACK_MODEL

    return None


def _build_model_chain(task: TaskType) -> list[str]:
    """Build ordered list of models to try for a task."""
    chain = [get_model(task)]

    fallback = get_fallback_model(task)
    if fallback and fallback not in chain:
        chain.append(fallback)

    # Last resort: explicit fallback model (if different from both)
    if settings.LLM_FALLBACK_MODEL and settings.LLM_FALLBACK_MODEL not in chain:
        chain.append(settings.LLM_FALLBACK_MODEL)

    return chain


async def cascaded_completion(
    task: TaskType,
    *,
    messages: list[dict],
    temperature: float = 0.2,
    **kwargs: Any,
) -> Any:
    """Call LLM with automatic model fallback on failure.

    Tries each model in the cascade chain. If the primary model fails
    (connection error, timeout, rate limit), falls back to the next model.

    Args:
        task: Task type for model selection.
        messages: Chat messages for the LLM.
        temperature: Sampling temperature.
        **kwargs: Additional args passed to litellm.acompletion.

    Returns:
        LiteLLM completion response.

    Raises:
        Exception: If all models in the chain fail.
    """
    chain = _build_model_chain(task)
    last_error = None

    import litellm

    for i, model_id in enumerate(chain):
        retries = settings.LLM_CASCADE_RETRIES if i == 0 else 1

        for attempt in range(retries):
            try:
                logger.debug(
                    "LLM cascade: %s → model=%s (attempt %d/%d)",
                    task.value, model_id, attempt + 1, retries,
                )
                response = await litellm.acompletion(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    timeout=settings.LLM_TIMEOUT_SECONDS,
                    **kwargs,
                )
                if i > 0:
                    logger.info(
                        "LLM cascade: %s succeeded on fallback model %s",
                        task.value, model_id,
                    )
                return response

            except Exception as e:
                last_error = e
                is_retriable = _is_retriable_error(e)
                logger.warning(
                    "LLM cascade: %s model=%s attempt %d failed (%s): %s",
                    task.value, model_id, attempt + 1,
                    "retriable" if is_retriable else "non-retriable",
                    str(e)[:200],
                )
                if not is_retriable:
                    break  # Skip remaining retries, try next model

    raise last_error  # type: ignore[misc]


def cascaded_completion_sync(
    task: TaskType,
    *,
    messages: list[dict],
    temperature: float = 0.2,
    **kwargs: Any,
) -> Any:
    """Synchronous version of cascaded_completion."""
    import litellm

    chain = _build_model_chain(task)
    last_error = None

    for i, model_id in enumerate(chain):
        retries = settings.LLM_CASCADE_RETRIES if i == 0 else 1

        for attempt in range(retries):
            try:
                response = litellm.completion(
                    model=model_id,
                    messages=messages,
                    temperature=temperature,
                    timeout=settings.LLM_TIMEOUT_SECONDS,
                    **kwargs,
                )
                if i > 0:
                    logger.info(
                        "LLM cascade: %s succeeded on fallback model %s",
                        task.value, model_id,
                    )
                return response

            except Exception as e:
                last_error = e
                if not _is_retriable_error(e):
                    break

    raise last_error  # type: ignore[misc]


def _is_retriable_error(e: Exception) -> bool:
    """Check if an error should trigger a retry vs immediate fallback."""
    error_str = str(e).lower()
    retriable_patterns = [
        "timeout",
        "rate_limit",
        "ratelimit",
        "429",
        "503",
        "502",
        "connection refused",
        "connection reset",
        "connection error",
        "temporary",
        "overloaded",
    ]
    return any(p in error_str for p in retriable_patterns)


def log_cascade_config() -> None:
    """Log the current model cascading configuration."""
    if not is_cascading_enabled():
        logger.info("Model cascading: disabled (using single model: %s)", settings.LLM_MODEL)
        return

    logger.info("Model cascading: enabled")
    for task in TaskType:
        chain = _build_model_chain(task)
        logger.info("  %s: %s", task.value, " → ".join(chain))
