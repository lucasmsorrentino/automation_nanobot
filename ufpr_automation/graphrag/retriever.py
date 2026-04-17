"""Graph-aware retrieval — combines Neo4j graph traversal with vector RAG.

Given an email's classification or content, this retriever:
1. Identifies relevant entities (workflows, norms, templates, systems)
2. Traverses the graph to find related context (hierarchy, steps, documents)
3. Formats the result for LLM injection alongside the vector RAG context

Usage:
    from ufpr_automation.graphrag.retriever import GraphRetriever

    retriever = GraphRetriever()
    context = retriever.get_context_for_email(email_subject, email_body, categoria)
    # Returns formatted string ready for LLM system prompt injection
"""

from __future__ import annotations

from typing import Any

from ufpr_automation.graphrag.client import Neo4jClient
from ufpr_automation.utils.logging import logger


class GraphRetriever:
    """Retrieves structured institutional knowledge from Neo4j for email processing."""

    def __init__(self, client: Neo4jClient | None = None) -> None:
        self._client = client or Neo4jClient()
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # High-level: get context for an email
    # ------------------------------------------------------------------

    def get_context_for_email(
        self,
        subject: str,
        body: str,
        categoria: str | None = None,
    ) -> str:
        """Return formatted graph context for an email classification/drafting task.

        Combines multiple graph queries into a single context string.
        """
        sections: list[str] = []

        # 1. Identify relevant workflow based on category + keywords
        fluxo = self._match_fluxo(subject, body, categoria)
        if fluxo:
            workflow_ctx = self._get_workflow_context(fluxo)
            if workflow_ctx:
                sections.append(workflow_ctx)

        # 2. Find applicable norms
        norms_ctx = self._get_norms_context(subject, body)
        if norms_ctx:
            sections.append(norms_ctx)

        # 3. Find relevant templates
        if fluxo:
            templates_ctx = self._get_templates_context(fluxo)
            if templates_ctx:
                sections.append(templates_ctx)

        # 4. SIGA navigation hints (if student-related)
        siga_ctx = self._get_siga_hints(subject, body)
        if siga_ctx:
            sections.append(siga_ctx)

        # 5. Organizational context (who to contact/escalate to)
        org_ctx = self._get_org_context(subject, body)
        if org_ctx:
            sections.append(org_ctx)

        if not sections:
            return ""

        header = "=== Contexto GraphRAG (Conhecimento Institucional) ==="
        return f"{header}\n\n" + "\n\n".join(sections)

    # ------------------------------------------------------------------
    # Workflow matching
    # ------------------------------------------------------------------

    def _match_fluxo(self, subject: str, body: str, categoria: str | None) -> str | None:
        """Match email content to a known workflow name."""
        text = f"{subject} {body}".lower()

        # Category-based matching
        if categoria:
            cat_lower = categoria.lower()
            if "estágio" in cat_lower or "estagio" in cat_lower:
                if any(k in text for k in ["aditivo", "prorrog", "renovar", "renov"]):
                    return "Termo Aditivo"
                if any(k in text for k in ["rescis", "encerr", "cancel", "deslig"]):
                    return "Rescisão"
                if any(k in text for k in ["certificad"]):
                    return "Certificação"
                if any(k in text for k in ["convalid", "aproveitament", "ic ", "iniciação"]):
                    return "Convalidação"
                if any(k in text for k in ["obrigatório", "od501", "odda5", "disciplina"]):
                    return "TCE Obrigatório"
                return "TCE Não Obrigatório"

        # Keyword-based fallback
        keyword_map = {
            "TCE Não Obrigatório": [
                "tce",
                "termo de compromisso",
                "estágio",
                "estagio",
                "novo estágio",
                "começar estágio",
                "iniciar estágio",
            ],
            "TCE Obrigatório": ["obrigatório", "od501", "odda5", "estágio supervisionado"],
            "Termo Aditivo": ["aditivo", "prorrogação", "prorrogar", "renovação", "renovar"],
            "Rescisão": ["rescisão", "encerramento", "cancelamento de estágio", "desligamento"],
            "Certificação": ["certificado", "certificação", "ficha de avaliação"],
            "Convalidação": ["convalidação", "aproveitamento", "ic como estágio"],
        }
        for fluxo_nome, keywords in keyword_map.items():
            if any(kw in text for kw in keywords):
                return fluxo_nome

        return None

    # ------------------------------------------------------------------
    # Query builders
    # ------------------------------------------------------------------

    def _get_workflow_context(self, fluxo_nome: str) -> str:
        """Get full workflow with steps, roles, and systems."""
        rows = self._client.run_query(
            """
            MATCH (f:Fluxo {nome: $nome})-[te:TEM_ETAPA]->(e:Etapa)
            OPTIONAL MATCH (e)-[:EXECUTADA_POR]->(p:Papel)
            OPTIONAL MATCH (e)-[:USA_SISTEMA]->(s:Sistema)
            RETURN f.nome AS fluxo, f.descricao AS desc, f.prazo AS prazo,
                   f.regra_bloqueio AS bloqueio,
                   e.ordem AS ordem, e.descricao AS etapa,
                   p.nome AS papel, s.nome AS sistema
            ORDER BY e.ordem
            """,
            {"nome": fluxo_nome},
        )
        if not rows:
            return ""

        first = rows[0]
        lines = [f"📋 Fluxo: {first['fluxo']} — {first['desc']}"]
        if first.get("prazo"):
            lines.append(f"⏰ Prazo: {first['prazo']}")
        if first.get("bloqueio"):
            lines.append(f"⚠️ Bloqueio: {first['bloqueio']}")
        lines.append("Etapas:")

        for row in rows:
            step = f"  {row['ordem']}. {row['etapa']}"
            meta = []
            if row.get("papel"):
                meta.append(f"por: {row['papel']}")
            if row.get("sistema"):
                meta.append(f"via: {row['sistema']}")
            if meta:
                step += f" [{', '.join(meta)}]"
            lines.append(step)

        return "\n".join(lines)

    def _get_norms_context(self, subject: str, body: str) -> str:
        """Find norms relevant to the email content via full-text search."""
        query_text = f"{subject} {body}"[:200]

        # Try full-text index first
        try:
            rows = self._client.run_query(
                """
                CALL db.index.fulltext.queryNodes('node_search', $query)
                YIELD node, score
                WHERE node:Norma AND score > 0.5
                RETURN node.codigo AS codigo, node.nome AS nome,
                       node.descricao AS desc, score
                ORDER BY score DESC
                LIMIT 5
                """,
                {"query": query_text},
            )
        except Exception:
            # Fallback: keyword matching
            rows = self._client.run_query(
                """
                MATCH (n:Norma)
                WHERE toLower(n.nome) CONTAINS toLower($kw)
                   OR toLower(n.descricao) CONTAINS toLower($kw)
                RETURN n.codigo AS codigo, n.nome AS nome, n.descricao AS desc, 1.0 AS score
                LIMIT 5
                """,
                {"kw": subject[:50]},
            )

        if not rows:
            return ""

        lines = ["📜 Normas aplicáveis:"]
        for row in rows:
            desc = f" — {row['desc']}" if row.get("desc") else ""
            lines.append(f"  • {row['codigo']}: {row['nome']}{desc}")
        return "\n".join(lines)

    def _get_templates_context(self, fluxo_nome: str) -> str:
        """Get email/despacho templates linked to a workflow."""
        rows = self._client.run_query(
            """
            MATCH (t:Template)-[:USADO_EM]->(f:Fluxo {nome: $nome})
            RETURN t.nome AS nome, t.tipo AS tipo, t.descricao AS desc
            ORDER BY t.tipo, t.nome
            """,
            {"nome": fluxo_nome},
        )
        if not rows:
            return ""

        lines = ["📝 Templates disponíveis:"]
        for row in rows:
            tipo_icon = "✉️" if "email" in row["tipo"] else "📄"
            lines.append(f"  {tipo_icon} {row['nome']}: {row['desc']}")
        return "\n".join(lines)

    def _get_siga_hints(self, subject: str, body: str) -> str:
        """Get SIGA navigation hints based on email keywords."""
        text = f"{subject} {body}".lower()

        # Check if this seems student-related
        student_keywords = [
            "aluno",
            "discente",
            "matrícula",
            "grr",
            "trancamento",
            "formatura",
            "integraliz",
            "histórico",
            "ira",
            "estágio",
        ]
        if not any(kw in text for kw in student_keywords):
            return ""

        rows = self._client.run_query(
            """
            MATCH (nav:SigaAba)-[:PERTENCE_A]->(s:Sistema {nome: 'SIGA'})
            RETURN nav.nome AS aba, nav.assunto AS assunto, nav.verificar AS verificar
            """
        )
        if not rows:
            return ""

        # Filter to relevant tabs
        relevant = []
        for row in rows:
            assunto_lower = row["assunto"].lower()
            if any(kw in text for kw in assunto_lower.split()):
                relevant.append(row)

        if not relevant:
            return ""

        lines = ["🖥️ Consultar no SIGA:"]
        for row in relevant:
            lines.append(
                f"  • Aba '{row['aba']}': {row['assunto']} → verificar: {row['verificar']}"
            )
        lines.append("  URL: https://siga.ufpr.br/siga/discente?operacao=listar&tipodiscente=I")
        return "\n".join(lines)

    def _get_org_context(self, subject: str, body: str) -> str:
        """Get organizational context (contacts, escalation paths)."""
        text = f"{subject} {body}".lower()

        queries: list[str] = []
        if any(kw in text for kw in ["estágio", "estagio", "tce", "coappe"]):
            queries.append("COAPPE")
        if any(kw in text for kw in ["progepe", "siape", "pagamento", "bolsa"]):
            queries.append("PROGEPE")
        if any(kw in text for kw in ["exterior", "internacional"]):
            queries.append("AUI")

        if not queries:
            return ""

        lines = ["🏛️ Contatos relevantes:"]
        for sigla in queries:
            rows = self._client.run_query(
                """
                MATCH (o:Orgao {sigla: $sigla})
                OPTIONAL MATCH (o)-[:SUBORDINADO_A]->(parent:Orgao)
                RETURN o.nome AS nome, o.email AS email, o.telefone AS tel,
                       o.descricao AS desc, parent.sigla AS parent_sigla
                """,
                {"sigla": sigla},
            )
            if rows:
                r = rows[0]
                contact = f"  • {r['nome']}"
                if r.get("email"):
                    contact += f" ({r['email']})"
                if r.get("tel"):
                    contact += f" | {r['tel']}"
                if r.get("parent_sigla"):
                    contact += f" [vinculado à {r['parent_sigla']}]"
                lines.append(contact)

        return "\n".join(lines) if len(lines) > 1 else ""

    # ------------------------------------------------------------------
    # Structured queries for sub-agents
    # ------------------------------------------------------------------

    def get_sei_process_type(self, assunto: str) -> dict[str, Any] | None:
        """Find the correct SEI process type for a given subject."""
        rows = self._client.run_query(
            """
            MATCH (tp:TipoProcesso)
            WHERE toLower(tp.nome) CONTAINS toLower($kw)
            RETURN tp.nome AS nome, tp.frequencia AS freq
            ORDER BY tp.frequencia DESC
            LIMIT 3
            """,
            {"kw": assunto},
        )
        return rows[0] if rows else None

    def get_workflow_steps(self, fluxo_nome: str) -> list[dict]:
        """Get ordered steps for a named workflow."""
        return self._client.run_query(
            """
            MATCH (f:Fluxo {nome: $nome})-[te:TEM_ETAPA]->(e:Etapa)
            OPTIONAL MATCH (e)-[:EXECUTADA_POR]->(p:Papel)
            OPTIONAL MATCH (e)-[:USA_SISTEMA]->(s:Sistema)
            RETURN e.ordem AS ordem, e.descricao AS descricao,
                   p.nome AS papel, s.nome AS sistema
            ORDER BY e.ordem
            """,
            {"nome": fluxo_nome},
        )

    def get_org_hierarchy(self, sigla: str, depth: int = 3) -> list[dict]:
        """Get organizational hierarchy upward from a given unit."""
        return self._client.run_query(
            """
            MATCH path = (o:Orgao {sigla: $sigla})-[:SUBORDINADO_A*1..%d]->(parent:Orgao)
            UNWIND nodes(path) AS node
            RETURN DISTINCT node.sigla AS sigla, node.nome AS nome
            """
            % depth,
            {"sigla": sigla},
        )

    def search_nodes(self, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across all indexed node types."""
        try:
            return self._client.run_query(
                """
                CALL db.index.fulltext.queryNodes('node_search', $query)
                YIELD node, score
                RETURN labels(node)[0] AS tipo, node.nome AS nome,
                       coalesce(node.sigla, node.codigo, '') AS id,
                       node.descricao AS descricao, score
                ORDER BY score DESC
                LIMIT $limit
                """,
                {"query": query, "limit": limit},
            )
        except Exception as e:
            logger.debug("Full-text search falhou: %s", e)
            return []

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Return node/relationship counts by label."""
        rows = self._client.run_query(
            """
            CALL db.labels() YIELD label
            CALL {
                WITH label
                MATCH (n)
                WHERE label IN labels(n)
                RETURN count(n) AS cnt
            }
            RETURN label, cnt
            ORDER BY cnt DESC
            """
        )
        result = {r["label"]: r["cnt"] for r in rows}
        result["_relationships"] = self._client.relationship_count()
        return result
