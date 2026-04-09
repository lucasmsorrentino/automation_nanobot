"""Offline DSPy prompt optimization script.

Usage:
    # Bootstrap with GEPA (no labeled data needed):
    python -m ufpr_automation.dspy_modules.optimize --strategy gepa

    # Optimize with MIPROv2 (requires feedback data with 50+ examples):
    python -m ufpr_automation.dspy_modules.optimize --strategy mipro

    # Evaluate current prompts without optimizing:
    python -m ufpr_automation.dspy_modules.optimize --evaluate-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import dspy

from ufpr_automation.config import settings
from ufpr_automation.dspy_modules.metrics import composite_metric
from ufpr_automation.dspy_modules.modules import SelfRefineModule
from ufpr_automation.utils.logging import logger

# Where optimized prompts are saved
OPTIMIZED_DIR = settings.PACKAGE_ROOT / "dspy_modules" / "optimized"


def _load_feedback_examples() -> list[dspy.Example]:
    """Load training examples from the feedback JSONL store."""
    feedback_path = settings.FEEDBACK_DATA_DIR / "feedback.jsonl"
    if not feedback_path.exists():
        logger.warning("Feedback file not found: %s", feedback_path)
        return []

    examples = []
    with open(feedback_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            corrected = record.get("corrected_classification", {})
            original = record.get("original_classification", {})

            # Build DSPy Example with inputs and expected outputs
            ex = dspy.Example(
                email_subject=record.get("email_subject", ""),
                email_body=record.get("email_body", ""),
                email_sender=record.get("email_sender", ""),
                rag_context="",
                # Expected outputs from human correction
                expected_categoria=corrected.get("categoria", original.get("categoria", "")),
            ).with_inputs("email_subject", "email_body", "email_sender", "rag_context")
            examples.append(ex)

    return examples


def _configure_lm():
    """Configure DSPy to use the project's LLM via LiteLLM."""
    lm = dspy.LM(
        model=f"litellm/{settings.LLM_MODEL}",
        temperature=0.2,
    )
    dspy.configure(lm=lm)
    return lm


def optimize_gepa(module: dspy.Module, examples: list[dspy.Example]) -> dspy.Module:
    """Optimize using GEPA (zero-shot bootstrap, no labeled data needed)."""
    from dspy.teleprompt import BootstrapFewShot

    optimizer = BootstrapFewShot(
        metric=composite_metric,
        max_bootstrapped_demos=4,
        max_labeled_demos=4,
    )

    if not examples:
        # Create synthetic examples for bootstrap
        examples = [
            dspy.Example(
                email_subject="Solicitacao de estagio obrigatorio",
                email_body="Prezado, solicito informacoes sobre o processo de estagio obrigatorio.",
                email_sender="aluno@ufpr.br",
                rag_context="",
                expected_categoria="Estagios",
            ).with_inputs("email_subject", "email_body", "email_sender", "rag_context"),
            dspy.Example(
                email_subject="Solicitacao de aproveitamento de disciplinas",
                email_body="Prezados, solicito aproveitamento de disciplinas cursadas em outra IES.",
                email_sender="aluno@ufpr.br",
                rag_context="",
                expected_categoria="Academico / Aproveitamento de Disciplinas",
            ).with_inputs("email_subject", "email_body", "email_sender", "rag_context"),
        ]

    compiled = optimizer.compile(module, trainset=examples)
    return compiled


def optimize_mipro(module: dspy.Module, examples: list[dspy.Example]) -> dspy.Module:
    """Optimize using MIPROv2 (requires labeled feedback data)."""
    if len(examples) < 20:
        logger.error(
            "MIPROv2 requires at least 20 feedback examples (have %d). "
            "Use --strategy gepa for bootstrap or collect more feedback.",
            len(examples),
        )
        sys.exit(1)

    from dspy.teleprompt import MIPROv2

    # Split into train/val
    split = int(len(examples) * 0.8)
    trainset = examples[:split]
    valset = examples[split:]

    optimizer = MIPROv2(
        metric=composite_metric,
        num_candidates=7,
        init_temperature=1.0,
    )

    compiled = optimizer.compile(
        module,
        trainset=trainset,
        valset=valset,
    )
    return compiled


def evaluate(module: dspy.Module, examples: list[dspy.Example]) -> float:
    """Evaluate module on examples and return average score."""
    if not examples:
        logger.warning("No examples to evaluate.")
        return 0.0

    from dspy.evaluate import Evaluate

    evaluator = Evaluate(
        devset=examples,
        metric=composite_metric,
        num_threads=1,
        display_progress=True,
    )
    score = evaluator(module)
    return score


def main():
    parser = argparse.ArgumentParser(description="DSPy prompt optimization for UFPR pipeline")
    parser.add_argument(
        "--strategy",
        choices=["gepa", "mipro"],
        default="gepa",
        help="Optimization strategy: gepa (bootstrap, no data) or mipro (requires feedback)",
    )
    parser.add_argument(
        "--evaluate-only",
        action="store_true",
        help="Only evaluate current prompts, don't optimize",
    )
    args = parser.parse_args()

    print("Configuring LLM...")
    _configure_lm()

    print("Loading feedback examples...")
    examples = _load_feedback_examples()
    print(f"  {len(examples)} example(s) loaded.")

    module = SelfRefineModule()

    if args.evaluate_only:
        print("\nEvaluating current prompts...")
        score = evaluate(module, examples)
        print(f"\nScore: {score:.2%}")
        return

    print(f"\nOptimizing with {args.strategy.upper()}...")
    if args.strategy == "gepa":
        compiled = optimize_gepa(module, examples)
    else:
        compiled = optimize_mipro(module, examples)

    # Save optimized module
    OPTIMIZED_DIR.mkdir(parents=True, exist_ok=True)
    save_path = OPTIMIZED_DIR / f"{args.strategy}_optimized.json"
    compiled.save(str(save_path))
    print(f"\nOptimized module saved to: {save_path}")

    # Evaluate optimized module
    if examples:
        print("\nEvaluating optimized module...")
        score = evaluate(compiled, examples)
        print(f"Optimized score: {score:.2%}")


if __name__ == "__main__":
    main()
