"""Quality metrics for DSPy optimization.

These metrics evaluate classification quality and are used by DSPy
optimizers (GEPA, MIPROv2) to score candidate prompts.
"""

from __future__ import annotations

from ufpr_automation.core.models import Categoria

# Valid categories (as a set for fast lookup)
VALID_CATEGORIES: set[str] = set(Categoria.__args__)


def category_valid(example, pred, trace=None) -> bool:
    """Check if the predicted category is one of the valid categories."""
    return pred.categoria in VALID_CATEGORIES


def category_match(example, pred, trace=None) -> bool:
    """Check if predicted category matches the expected category."""
    expected = getattr(example, "expected_categoria", None)
    if expected is None:
        return True  # no ground truth available
    return pred.categoria == expected


def response_not_empty(example, pred, trace=None) -> bool:
    """Check that a response was generated when one was expected."""
    # If action requires response, sugestao_resposta shouldn't be empty
    action = pred.acao_necessaria.lower()
    needs_response = any(kw in action for kw in ("redigir", "responder", "resposta", "enviar"))
    if needs_response:
        return bool(pred.sugestao_resposta.strip())
    return True


def confidence_reasonable(example, pred, trace=None) -> bool:
    """Check that confidence is a reasonable float in [0, 1]."""
    try:
        conf = float(pred.confianca)
        return 0.0 <= conf <= 1.0
    except (ValueError, TypeError):
        return False


def formal_tone(example, pred, trace=None) -> float:
    """Score the formality of the draft response (0.0 to 1.0).

    Heuristic: checks for formal markers common in Brazilian
    institutional correspondence.
    """
    text = pred.sugestao_resposta
    if not text.strip():
        return 1.0  # no response needed = no penalty

    score = 0.0
    markers = [
        "prezado",
        "prezada",
        "atenciosamente",
        "cordialmente",
        "senhor",
        "senhora",
        "informamos",
        "encaminhamos",
        "solicitamos",
        "segue em anexo",
    ]
    text_lower = text.lower()
    found = sum(1 for m in markers if m in text_lower)
    score = min(1.0, found / 3.0)  # 3+ markers = full score
    return score


def composite_metric(example, pred, trace=None) -> float:
    """Composite metric combining all quality checks.

    Returns a float between 0.0 and 1.0 used by DSPy optimizers.
    """
    scores = []

    # Category validity (binary)
    scores.append(1.0 if category_valid(example, pred) else 0.0)

    # Category match (binary, if ground truth available)
    scores.append(1.0 if category_match(example, pred) else 0.0)

    # Response completeness (binary)
    scores.append(1.0 if response_not_empty(example, pred) else 0.0)

    # Confidence validity (binary)
    scores.append(1.0 if confidence_reasonable(example, pred) else 0.0)

    # Formal tone (gradient)
    scores.append(formal_tone(example, pred))

    return sum(scores) / len(scores)
