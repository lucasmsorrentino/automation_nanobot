"""RAG (Retrieval-Augmented Generation) module for UFPR institutional documents."""

from ufpr_automation.rag.ingest import ingest_docs
from ufpr_automation.rag.raptor import RaptorRetriever
from ufpr_automation.rag.retriever import Retriever

__all__ = ["ingest_docs", "Retriever", "RaptorRetriever"]
