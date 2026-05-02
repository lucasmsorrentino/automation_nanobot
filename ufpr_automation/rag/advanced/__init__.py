"""Optional/advanced RAG features.

Modulos aqui sao **opcionais** — o caminho de retrieval default e
``ufpr_automation.rag.retriever.Retriever`` (busca flat sobre LanceDB).
Os modulos deste pacote so sao usados quando explicitamente ativados:

- ``raptor.py`` — RAPTOR hierarchical retrieval (GMM clustering +
  recursive LLM summarization). Ativo automaticamente em
  ``graph.nodes:_get_retriever`` se a tabela ``ufpr_raptor`` existe no
  LanceDB. Build via ``python -m ufpr_automation.rag.advanced.raptor``.
"""
