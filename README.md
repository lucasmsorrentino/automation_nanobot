# UFPR Email Automation

This repository hosts the UFPR (Universidade Federal do Paraná) email automation
project: a pipeline that reads institutional emails, classifies them via LLM,
retrieves context from normative documents (vector RAG + Neo4j knowledge graph),
and saves draft replies for human review. The project never auto-sends.

The codebase originated from a fork of the [nanobot-ai](https://github.com/nanobots-ai/nanobot)
agent framework, but the active project here is `ufpr_automation/`. The
`nanobot/` package is kept as the underlying agent runtime.

## Where to look

- **[`ufpr_automation/README.md`](ufpr_automation/README.md)** — project
  overview, quickstart, CLI commands, and feature reference.
- **[`ufpr_automation/ARCHITECTURE.md`](ufpr_automation/ARCHITECTURE.md)** —
  architecture diagrams (LangGraph Fleet, RAG, GraphRAG, Hybrid Memory) and
  the Marco I → V maturation roadmap.
- **[`CLAUDE.md`](CLAUDE.md)** — instructions for Claude Code / AI coding
  agents working in this repo.

## License

MIT — see [`LICENSE`](LICENSE). Original copyright by the nanobot contributors
(upstream attribution preserved).
