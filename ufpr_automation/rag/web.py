"""Web UI (Streamlit) for querying the UFPR RAG vector store.

Usage:
    streamlit run ufpr_automation/rag/web.py
    python -m streamlit run ufpr_automation/rag/web.py -- --port 8501
"""

from __future__ import annotations

import streamlit as st

from ufpr_automation.rag.retriever import Retriever

CONSELHOS = ["todos", "cepe", "coun", "coplad", "concur", "estagio"]
TIPOS = ["todos", "atas", "resolucoes", "instrucoes-normativas", "estagio"]


@st.cache_resource(show_spinner="Carregando modelo de embeddings...")
def load_retriever() -> Retriever:
    """Load retriever once and cache across reruns."""
    r = Retriever()
    r._ensure_loaded()
    return r


def main():
    st.set_page_config(
        page_title="UFPR RAG — Consulta de Documentos",
        page_icon="🔍",
        layout="wide",
    )

    st.title("🔍 UFPR RAG — Consulta de Documentos Institucionais")
    st.caption(
        "Busca semântica em resoluções, atas, instruções normativas "
        "e documentos de estágio da UFPR."
    )

    retriever = load_retriever()

    # --- Sidebar: filters ---
    with st.sidebar:
        st.header("Filtros")
        conselho = st.selectbox("Conselho", CONSELHOS, index=0)
        tipo = st.selectbox("Tipo de Documento", TIPOS, index=0)
        top_k = st.slider("Quantidade de Resultados", min_value=1, max_value=20, value=5)

        st.divider()
        st.markdown(
            "**Stack:** LanceDB + multilingual-e5-large\n\n"
            "**Dados:** [soc.ufpr.br](https://soc.ufpr.br)"
        )

    # --- Main: search ---
    query = st.text_input(
        "Consulta",
        placeholder="Ex: prazo máximo para estágio obrigatório",
    )

    if query.strip():
        results = retriever.search(
            query,
            conselho=conselho if conselho != "todos" else None,
            tipo=tipo if tipo != "todos" else None,
            top_k=top_k,
        )

        if not results:
            st.warning("Nenhum resultado encontrado.")
        else:
            st.subheader(f"{len(results)} resultado(s)")

            for i, res in enumerate(results, 1):
                # Score color indicator
                if res.score < 0.25:
                    score_badge = f":green[{res.score:.4f}]"
                elif res.score < 0.4:
                    score_badge = f":orange[{res.score:.4f}]"
                else:
                    score_badge = f":red[{res.score:.4f}]"

                with st.expander(
                    f"**[{i}]** {res.caminho}  —  score: {res.score:.4f}",
                    expanded=i <= 3,
                ):
                    cols = st.columns([1, 1, 1])
                    cols[0].metric("Score", f"{res.score:.4f}")
                    cols[1].markdown(f"**Conselho:** `{res.conselho}`")
                    cols[2].markdown(f"**Tipo:** `{res.tipo}`")

                    st.markdown(f"**Arquivo:** `{res.arquivo}` — chunk {res.chunk_idx}")
                    st.divider()
                    st.markdown(res.text)


if __name__ == "__main__":
    main()
