"""DSPy Modules for the UFPR email pipeline.

Modules compose Signatures into executable pipelines that DSPy can optimize.
Each module wraps one or more Signatures with control flow logic.
"""

from __future__ import annotations

import dspy

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.dspy_modules.signatures import (
    DraftCritic,
    DraftRefiner,
    EmailClassifier,
)


class EmailClassifierModule(dspy.Module):
    """Classify an email and generate a draft response.

    Wraps the EmailClassifier Signature in a dspy.Predict call.
    Can be used standalone or as part of a larger pipeline.
    """

    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(EmailClassifier)

    def forward(
        self,
        email_subject: str,
        email_body: str,
        email_sender: str,
        rag_context: str = "",
    ) -> dspy.Prediction:
        return self.classify(
            email_subject=email_subject,
            email_body=email_body,
            email_sender=email_sender,
            rag_context=rag_context,
        )


class SelfRefineModule(dspy.Module):
    """Classify -> Critique -> Refine pipeline (Self-Refine pattern).

    Implements the generate-critique-refine cycle from Madaan et al. (NeurIPS 2023).
    If the critic finds no issues, returns the original classification unchanged.
    """

    def __init__(self):
        super().__init__()
        self.classify = dspy.Predict(EmailClassifier)
        self.critique = dspy.Predict(DraftCritic)
        self.refine = dspy.Predict(DraftRefiner)

    def forward(
        self,
        email_subject: str,
        email_body: str,
        email_sender: str,
        rag_context: str = "",
    ) -> dspy.Prediction:
        # Step 1: Classify
        classification = self.classify(
            email_subject=email_subject,
            email_body=email_body,
            email_sender=email_sender,
            rag_context=rag_context,
        )

        # Step 2: Critique
        critic_result = self.critique(
            email_subject=email_subject,
            email_body=email_body,
            draft_response=classification.sugestao_resposta,
            categoria=classification.categoria,
            rag_context=rag_context,
        )

        # Step 3: Refine (only if issues found)
        if critic_result.has_issues:
            refined = self.refine(
                email_subject=email_subject,
                email_body=email_body,
                original_draft=classification.sugestao_resposta,
                critique=critic_result.critique,
                rag_context=rag_context,
            )
            return refined

        return classification


_VALID_CATEGORIES = [
    "Estágios", "Ofícios", "Memorandos", "Requerimentos",
    "Portarias", "Informes", "Urgente", "Correio Lixo", "Outros",
]

# Map common LLM free-form outputs to valid categories
_CATEGORY_ALIASES: dict[str, str] = {
    "estagio": "Estágios", "estagios": "Estágios", "estágio": "Estágios",
    "estágios": "Estágios", "termo aditivo": "Estágios", "tce": "Estágios",
    "oficio": "Ofícios", "oficios": "Ofícios", "ofício": "Ofícios",
    "ofícios": "Ofícios",
    "memorando": "Memorandos", "memorandos": "Memorandos",
    "requerimento": "Requerimentos", "requerimentos": "Requerimentos",
    "solicitação": "Requerimentos", "solicitacao": "Requerimentos",
    "portaria": "Portarias", "portarias": "Portarias",
    "informe": "Informes", "informes": "Informes", "informativo": "Informes",
    "divulgação": "Informes", "divulgacao": "Informes", "convite": "Informes",
    "urgente": "Urgente", "urgência": "Urgente",
    "spam": "Correio Lixo", "correio lixo": "Correio Lixo", "lixo": "Correio Lixo",
    "propaganda": "Correio Lixo", "promocional": "Correio Lixo",
    "outros": "Outros",
    # Common free-form responses from the LLM
    "coordenação": "Informes", "coordenacao": "Informes",
    "consulta": "Requerimentos", "dúvida": "Requerimentos", "duvida": "Requerimentos",
    "colação": "Requerimentos", "colacao": "Requerimentos",
    "ementa": "Requerimentos", "ementas": "Requerimentos",
    "horas formativas": "Requerimentos",
    "processo": "Ofícios",
}


def _normalize_categoria(raw: str) -> str:
    """Normalize a free-form category string to a valid Categoria literal."""
    stripped = raw.strip()
    # Exact match (case-insensitive)
    for valid in _VALID_CATEGORIES:
        if stripped.lower() == valid.lower():
            return valid
    # Alias match
    key = stripped.lower()
    if key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[key]
    # Substring match — check if any alias keyword appears in the raw string
    for alias, mapped in _CATEGORY_ALIASES.items():
        if alias in key:
            return mapped
    # Default fallback
    return "Outros"


def prediction_to_classification(pred: dspy.Prediction) -> EmailClassification:
    """Convert a DSPy Prediction to an EmailClassification model."""
    confianca = pred.confianca
    if isinstance(confianca, str):
        try:
            confianca = float(confianca)
        except (ValueError, TypeError):
            confianca = 0.5
    confianca = max(0.0, min(1.0, confianca))

    return EmailClassification(
        categoria=_normalize_categoria(pred.categoria),
        resumo=pred.resumo,
        acao_necessaria=pred.acao_necessaria,
        sugestao_resposta=pred.sugestao_resposta,
        confianca=confianca,
    )


def classify_email_dspy(
    email: EmailData,
    rag_context: str = "",
    use_self_refine: bool = True,
) -> EmailClassification:
    """Classify an email using DSPy modules.

    This is the main entry point for DSPy-based classification,
    intended to replace LLMClient.classify_email() when DSPy is enabled.

    Args:
        email: The email to classify.
        rag_context: RAG-retrieved context string.
        use_self_refine: Whether to use the Self-Refine pipeline.

    Returns:
        EmailClassification with the LLM's analysis.
    """
    body = email.body or email.preview

    if use_self_refine:
        module = SelfRefineModule()
    else:
        module = EmailClassifierModule()

    pred = module(
        email_subject=email.subject,
        email_body=body,
        email_sender=email.sender,
        rag_context=rag_context,
    )

    return prediction_to_classification(pred)
