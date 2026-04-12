---
description: Run a semantic RAG query against the institutional doc store
argument-hint: "<query text>"
allowed-tools: Bash(python -m ufpr_automation.rag.retriever:*)
---

Run a semantic RAG query against the 34K-chunk UFPR institutional doc store
and return the top 5 matches. Use this to check if the RAG has coverage on a
given topic before drafting an intent or reply.

!`python -m ufpr_automation.rag.retriever "$ARGUMENTS" --top-k 5`
