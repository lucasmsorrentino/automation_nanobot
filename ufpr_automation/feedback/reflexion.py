"""Reflexion — Episodic memory of past errors for self-improvement.

When a human corrects a draft, this module:
1. Generates an analysis of what went wrong (via LLM)
2. Stores the reflection in a vector store
3. On future classifications, retrieves similar past errors as negative context

This prevents the system from repeating the same mistakes.

Reference:
    Shinn et al., "Reflexion: Language Agents with Verbal Reinforcement
    Learning", NeurIPS 2023.

Usage:
    from ufpr_automation.feedback.reflexion import ReflexionMemory

    memory = ReflexionMemory()
    memory.add_reflection(email, original_cls, corrected_cls)
    past_errors = memory.retrieve("estagio obrigatorio", top_k=3)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailClassification
from ufpr_automation.utils.logging import logger

REFLEXION_DIR = settings.FEEDBACK_DATA_DIR
REFLEXION_FILE = REFLEXION_DIR / "reflexions.jsonl"
REFLEXION_STORE = settings.RAG_STORE_DIR / "ufpr.lance"
REFLEXION_TABLE = "ufpr_reflexions"


class ReflexionMemory:
    """Episodic memory storing analyses of past classification errors."""

    def __init__(self):
        self._db = None
        self._table = None
        self._model = None

    def _ensure_store(self):
        """Lazy-load LanceDB and embedding model."""
        if self._db is not None:
            return

        import lancedb
        from sentence_transformers import SentenceTransformer

        REFLEXION_DIR.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(REFLEXION_STORE))
        self._model = SentenceTransformer("intfloat/multilingual-e5-large")

        if REFLEXION_TABLE in self._db.list_tables().tables:
            self._table = self._db.open_table(REFLEXION_TABLE)

    def _embed(self, text: str) -> list[float]:
        """Embed text for vector search."""
        vec = self._model.encode(f"passage: {text}", normalize_embeddings=True)
        return vec.tolist()

    def _embed_query(self, text: str) -> list[float]:
        vec = self._model.encode(f"query: {text}", normalize_embeddings=True)
        return vec.tolist()

    def generate_reflection(
        self,
        email_subject: str,
        email_body: str,
        original: EmailClassification,
        corrected: EmailClassification,
    ) -> str:
        """Use the LLM to analyze what went wrong in the original classification.

        Args:
            email_subject: Subject of the misclassified email.
            email_body: Body (or preview) of the email.
            original: The system's incorrect classification.
            corrected: The human-corrected classification.

        Returns:
            A textual reflection analyzing the error.
        """
        import litellm

        prompt = (
            "Analise o erro de classificacao abaixo e explique de forma concisa "
            "o que deu errado e como evitar o mesmo erro no futuro.\n\n"
            f"E-mail:\n  Assunto: {email_subject}\n  Corpo: {email_body[:400]}\n\n"
            f"Classificacao original (ERRADA):\n"
            f"  Categoria: {original.categoria}\n"
            f"  Resumo: {original.resumo}\n"
            f"  Acao: {original.acao_necessaria}\n"
            f"  Resposta: {original.sugestao_resposta[:300]}\n\n"
            f"Correcao humana (CERTA):\n"
            f"  Categoria: {corrected.categoria}\n"
            f"  Resumo: {corrected.resumo}\n"
            f"  Acao: {corrected.acao_necessaria}\n"
            f"  Resposta: {corrected.sugestao_resposta[:300]}\n\n"
            "Reflexao (em 2-3 sentencas, foque no ERRO e como evitar):"
        )

        try:
            response = litellm.completion(
                model=settings.LLM_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Falha ao gerar reflexao: %s", e)
            # Fallback: simple diff description
            changes = []
            if original.categoria != corrected.categoria:
                changes.append(
                    f"Categoria errada: '{original.categoria}' deveria ser '{corrected.categoria}'"
                )
            if original.acao_necessaria != corrected.acao_necessaria:
                changes.append(
                    f"Acao errada: '{original.acao_necessaria}' deveria ser '{corrected.acao_necessaria}'"
                )
            return ". ".join(changes) if changes else "Resposta corrigida pelo revisor."

    def add_reflection(
        self,
        email_subject: str,
        email_body: str,
        original: EmailClassification,
        corrected: EmailClassification,
        reflection_text: str | None = None,
    ) -> str:
        """Generate and store a reflection for a classification error.

        Args:
            email_subject: Subject of the email.
            email_body: Body of the email.
            original: Original (incorrect) classification.
            corrected: Human-corrected classification.
            reflection_text: Pre-generated reflection (skips LLM call if provided).

        Returns:
            The reflection text.
        """
        self._ensure_store()

        # Generate reflection if not provided
        if reflection_text is None:
            reflection_text = self.generate_reflection(
                email_subject, email_body, original, corrected
            )

        # Save to JSONL (persistent log)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "email_subject": email_subject,
            "original_categoria": original.categoria,
            "corrected_categoria": corrected.categoria,
            "reflection": reflection_text,
        }
        REFLEXION_DIR.mkdir(parents=True, exist_ok=True)
        with open(REFLEXION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # Index in vector store for semantic retrieval
        context = f"{email_subject} | {reflection_text}"
        vector = self._embed(context)

        entry = {
            "text": reflection_text,
            "vector": vector,
            "email_subject": email_subject,
            "original_categoria": original.categoria,
            "corrected_categoria": corrected.categoria,
            "timestamp": record["timestamp"],
        }

        if self._table is None:
            self._table = self._db.create_table(REFLEXION_TABLE, data=[entry])
        else:
            self._table.add([entry])

        logger.info("Reflexion salva: [%s -> %s] %s", original.categoria, corrected.categoria, email_subject[:40])
        return reflection_text

    def retrieve(self, query: str, top_k: int = 3) -> list[dict]:
        """Retrieve past reflections relevant to a query.

        Args:
            query: Search query (e.g., email subject + body excerpt).
            top_k: Number of reflections to return.

        Returns:
            List of reflection dicts with text, score, and metadata.
        """
        self._ensure_store()

        if self._table is None:
            return []

        query_vec = self._embed_query(query)
        tbl = self._table.search(query_vec).limit(top_k).to_arrow()

        results = []
        for i in range(tbl.num_rows):
            results.append({
                "text": tbl.column("text")[i].as_py(),
                "score": float(tbl.column("_distance")[i].as_py()),
                "original_categoria": tbl.column("original_categoria")[i].as_py(),
                "corrected_categoria": tbl.column("corrected_categoria")[i].as_py(),
                "email_subject": tbl.column("email_subject")[i].as_py(),
            })
        return results

    def retrieve_formatted(self, query: str, top_k: int = 3) -> str:
        """Retrieve and format reflections for LLM context injection.

        Returns a string that can be injected into the classification prompt
        as negative examples (past errors to avoid).
        """
        results = self.retrieve(query, top_k=top_k)
        if not results:
            return ""

        parts = ["=== ERROS ANTERIORES (evitar repetir) ==="]
        for i, r in enumerate(results, 1):
            parts.append(
                f"[{i}] Assunto: {r['email_subject']}\n"
                f"    Erro: classificado como '{r['original_categoria']}', "
                f"correto era '{r['corrected_categoria']}'\n"
                f"    Reflexao: {r['text']}"
            )
        return "\n\n".join(parts)

    def count(self) -> int:
        """Count total stored reflections."""
        if not REFLEXION_FILE.exists():
            return 0
        with open(REFLEXION_FILE, "r", encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
