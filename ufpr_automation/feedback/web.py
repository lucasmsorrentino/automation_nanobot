"""Web UI (Streamlit) for reviewing agent work and providing feedback.

Provides a dashboard for the human reviewer to:
1. See pipeline execution summaries
2. Review and correct email classifications
3. Approve or edit draft responses
4. View SEI/SIGA consultation results
5. Track learning statistics over time
6. Browse procedure logs

Usage:
    streamlit run ufpr_automation/feedback/web.py
    streamlit run ufpr_automation/feedback/web.py -- --port 8502
"""

from __future__ import annotations

import json

import streamlit as st

from ufpr_automation.config import settings
from ufpr_automation.core.models import EmailClassification
from ufpr_automation.feedback.store import FeedbackStore

# Valid categories (kept in sync with core/models.py)
_VALID_CATEGORIES = [
    "Estágios",
    "Acadêmico / Matrícula",
    "Acadêmico / Equivalência de Disciplinas",
    "Acadêmico / Aproveitamento de Disciplinas",
    "Acadêmico / Ajuste de Disciplinas",
    "Diplomação / Diploma",
    "Diplomação / Colação de Grau",
    "Extensão",
    "Formativas",
    "Requerimentos",
    "Urgente",
    "Correio Lixo",
    "Outros",
]

FEEDBACK_DIR = settings.FEEDBACK_DATA_DIR
PROCEDURES_DIR = settings.PROCEDURES_DATA_DIR


@st.cache_resource
def get_feedback_store() -> FeedbackStore:
    return FeedbackStore()


def load_last_run() -> list[dict]:
    """Load entries from the last pipeline run."""
    results_file = FEEDBACK_DIR / "last_run.jsonl"
    if not results_file.exists():
        return []
    entries = []
    with open(results_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def load_procedures() -> list[dict]:
    """Load procedure records."""
    proc_file = PROCEDURES_DIR / "procedures.jsonl"
    if not proc_file.exists():
        return []
    records = []
    with open(proc_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def page_dashboard():
    """Dashboard: summary of recent pipeline executions."""
    st.header("Dashboard")

    store = get_feedback_store()
    last_run = load_last_run()
    procedures = load_procedures()
    feedback_records = store.list_all()

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Emails (ultimo run)", len(last_run))
    with col2:
        st.metric("Total Feedbacks", len(feedback_records))
    with col3:
        st.metric("Total Procedimentos", len(procedures))
    with col4:
        sei_count = sum(1 for p in procedures if p.get("sei_process"))
        siga_count = sum(1 for p in procedures if p.get("siga_grr"))
        st.metric("Consultas SEI/SIGA", f"{sei_count}/{siga_count}")

    if last_run:
        st.subheader("Ultimo pipeline")
        for entry in last_run:
            cls = entry.get("classification", {})
            cat = cls.get("categoria", "?")
            conf = cls.get("confianca", 0)
            icon = "🟢" if conf >= 0.95 else ("🟡" if conf >= 0.7 else "🔴")
            with st.expander(
                f"{icon} [{cat}] {entry.get('subject', '?')[:60]}  (confianca: {conf:.0%})"
            ):
                st.text(f"De: {entry.get('sender', '?')}")
                st.text(f"Resumo: {cls.get('resumo', '-')}")
                st.text(f"Acao: {cls.get('acao_necessaria', '-')}")
                resposta = cls.get("sugestao_resposta", "")
                if resposta:
                    st.text_area("Rascunho gerado", resposta, height=150, disabled=True)


def page_review():
    """Review classifications from the last pipeline run."""
    st.header("Revisar Classificacoes")

    store = get_feedback_store()
    last_run = load_last_run()

    if not last_run:
        st.info(
            "Nenhum resultado de pipeline encontrado. "
            "Execute o pipeline primeiro: `python -m ufpr_automation --channel gmail --langgraph`"
        )
        return

    st.write(f"**{len(last_run)} classificacao(oes) para revisao**")

    for i, entry in enumerate(last_run):
        email_hash = entry.get("email_hash", "unknown")
        sender = entry.get("sender", "?")
        subject = entry.get("subject", "?")
        cls_data = entry.get("classification", {})
        cat = cls_data.get("categoria", "?")
        conf = cls_data.get("confianca", 0)

        with st.expander(f"[{i + 1}/{len(last_run)}] {subject[:60]} ({cat}, {conf:.0%})"):
            st.text(f"De: {sender}")
            st.text(f"Resumo: {cls_data.get('resumo', '-')}")
            st.text(f"Acao: {cls_data.get('acao_necessaria', '-')}")

            resposta = cls_data.get("sugestao_resposta", "")
            if resposta:
                st.text_area(
                    "Rascunho",
                    resposta,
                    height=150,
                    disabled=True,
                    key=f"draft_{i}",
                )

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("Aceitar", key=f"accept_{i}"):
                    original = EmailClassification(**cls_data)
                    store.add(
                        email_hash=email_hash,
                        original=original,
                        corrected=original,
                        email_sender=sender,
                        email_subject=subject,
                        notes="accepted via web UI",
                    )
                    st.success("Aceito e registrado!")

            with col_b:
                if st.button("Corrigir", key=f"correct_{i}"):
                    st.session_state[f"correcting_{i}"] = True

            if st.session_state.get(f"correcting_{i}", False):
                new_cat = st.selectbox(
                    "Nova categoria",
                    _VALID_CATEGORIES,
                    index=_VALID_CATEGORIES.index(cat) if cat in _VALID_CATEGORIES else 0,
                    key=f"new_cat_{i}",
                )
                new_resumo = st.text_input(
                    "Novo resumo",
                    value=cls_data.get("resumo", ""),
                    key=f"new_resumo_{i}",
                )
                new_resposta = st.text_area(
                    "Nova resposta",
                    value=resposta,
                    height=150,
                    key=f"new_resp_{i}",
                )
                notes = st.text_input("Notas (opcional)", key=f"notes_{i}")

                if st.button("Salvar correcao", key=f"save_corr_{i}"):
                    original = EmailClassification(**cls_data)
                    corrected_data = dict(cls_data)
                    corrected_data["categoria"] = new_cat
                    corrected_data["resumo"] = new_resumo
                    if new_resposta != resposta:
                        corrected_data["sugestao_resposta"] = new_resposta
                    corrected = EmailClassification(**corrected_data)

                    store.add(
                        email_hash=email_hash,
                        original=original,
                        corrected=corrected,
                        email_sender=sender,
                        email_subject=subject,
                        notes=notes or "corrected via web UI",
                    )

                    # Generate Reflexion if category changed
                    if original.categoria != corrected.categoria:
                        try:
                            from ufpr_automation.feedback.reflexion import ReflexionMemory

                            memory = ReflexionMemory()
                            memory.add_reflection(
                                email_subject=subject,
                                email_body=entry.get("body", ""),
                                original=original,
                                corrected=corrected,
                            )
                            st.info("Reflexion gerada para correcao")
                        except Exception:
                            pass

                    st.success(f"Correcao salva: {cat} -> {new_cat}")
                    st.session_state[f"correcting_{i}"] = False


def page_statistics():
    """Statistics and learning progress."""
    st.header("Estatisticas de Aprendizado")

    store = get_feedback_store()
    records = store.list_all()
    procedures = load_procedures()

    if not records and not procedures:
        st.info("Nenhum dado disponivel ainda. Execute o pipeline e forneca feedback.")
        return

    # Feedback stats
    if records:
        st.subheader("Feedback Acumulado")
        st.metric("Total de registros", len(records))

        # Category corrections
        corrections = {}
        agreements = 0
        for r in records:
            if r.original.categoria != r.corrected.categoria:
                key = f"{r.original.categoria} -> {r.corrected.categoria}"
                corrections[key] = corrections.get(key, 0) + 1
            else:
                agreements += 1

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Classificacoes corretas", agreements)
        with col2:
            st.metric("Correcoes feitas", len(records) - agreements)

        if corrections:
            st.write("**Correcoes mais frequentes:**")
            for change, count in sorted(corrections.items(), key=lambda x: -x[1]):
                st.text(f"  {change}: {count}x")

        # Accuracy over time (by date)
        by_date: dict[str, dict[str, int]] = {}
        for r in records:
            date = r.timestamp[:10]
            by_date.setdefault(date, {"correct": 0, "corrected": 0})
            if r.original.categoria == r.corrected.categoria:
                by_date[date]["correct"] += 1
            else:
                by_date[date]["corrected"] += 1

        if len(by_date) > 1:
            st.subheader("Evolucao da acuracia")
            chart_data = []
            for date in sorted(by_date.keys()):
                d = by_date[date]
                total = d["correct"] + d["corrected"]
                accuracy = d["correct"] / total if total > 0 else 0
                chart_data.append({"date": date, "acuracia": accuracy, "total": total})
            st.line_chart(
                {d["date"]: d["acuracia"] for d in chart_data},
            )

    # Procedure stats
    if procedures:
        st.subheader("Procedimentos")

        by_outcome: dict[str, int] = {}
        by_cat: dict[str, int] = {}
        durations: list[int] = []

        for p in procedures:
            outcome = p.get("outcome", "?")
            by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
            cat = p.get("email_categoria", "?")
            by_cat[cat] = by_cat.get(cat, 0) + 1
            durations.append(p.get("total_duration_ms", 0))

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total procedimentos", len(procedures))
        with col2:
            avg_ms = sum(durations) // len(durations) if durations else 0
            st.metric("Duracao media", f"{avg_ms}ms")
        with col3:
            sei_count = sum(1 for p in procedures if p.get("sei_process"))
            st.metric("Consultas SEI", sei_count)

        if by_outcome:
            st.write("**Por resultado:**")
            for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
                st.text(f"  {outcome}: {count}")

        if by_cat:
            st.write("**Por categoria:**")
            for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
                st.text(f"  {cat}: {count}")


def page_procedures():
    """Browse procedure execution logs."""
    st.header("Log de Procedimentos")

    procedures = load_procedures()
    if not procedures:
        st.info("Nenhum procedimento registrado ainda.")
        return

    # Filters
    col1, col2 = st.columns(2)
    with col1:
        outcomes = sorted(set(p.get("outcome", "?") for p in procedures))
        filter_outcome = st.selectbox("Filtrar por resultado", ["todos"] + outcomes)
    with col2:
        cats = sorted(set(p.get("email_categoria", "?") for p in procedures))
        filter_cat = st.selectbox("Filtrar por categoria", ["todos"] + cats)

    filtered = procedures
    if filter_outcome != "todos":
        filtered = [p for p in filtered if p.get("outcome") == filter_outcome]
    if filter_cat != "todos":
        filtered = [p for p in filtered if p.get("email_categoria") == filter_cat]

    st.write(f"**{len(filtered)} procedimento(s)**")

    for p in reversed(filtered[-50:]):  # Show latest 50
        ts = p.get("timestamp", "?")[:19]
        subject = p.get("email_subject", "?")[:50]
        outcome = p.get("outcome", "?")
        cat = p.get("email_categoria", "?")
        duration = p.get("total_duration_ms", 0)

        with st.expander(f"[{ts}] {subject} — {outcome} ({cat}, {duration}ms)"):
            if p.get("sei_process"):
                st.text(f"Processo SEI: {p['sei_process']}")
            if p.get("siga_grr"):
                st.text(f"GRR consultado: {p['siga_grr']}")
            if p.get("human_feedback"):
                st.text(f"Feedback humano: {p['human_feedback']}")

            steps = p.get("steps", [])
            if steps:
                st.write("**Etapas:**")
                for s in steps:
                    icon = "✅" if s.get("result") == "ok" else "❌"
                    st.text(
                        f"  {icon} {s.get('name', '?')} — "
                        f"{s.get('duration_ms', 0)}ms — {s.get('result', '?')}"
                    )
                    if s.get("notes"):
                        st.text(f"     Notas: {s['notes']}")


def main():
    st.set_page_config(
        page_title="UFPR Automation — Feedback",
        page_icon="📋",
        layout="wide",
    )

    st.title("📋 UFPR Automation — Painel de Feedback")
    st.caption(
        "Revise o trabalho do agente, corrija classificacoes e acompanhe a evolucao do aprendizado."
    )

    page = st.sidebar.radio(
        "Pagina",
        ["Dashboard", "Revisar Classificacoes", "Estatisticas", "Procedimentos"],
    )

    if page == "Dashboard":
        page_dashboard()
    elif page == "Revisar Classificacoes":
        page_review()
    elif page == "Estatisticas":
        page_statistics()
    elif page == "Procedimentos":
        page_procedures()


if __name__ == "__main__":
    main()
