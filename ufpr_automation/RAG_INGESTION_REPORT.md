# Relatório de Ingestão RAG

**Última atualização:** 2026-04-07 (com OCR Tesseract)
**Comando:** `python -m ufpr_automation.rag.ingest [--ocr-only]`

## Resumo

| Métrica | Valor |
|---|---|
| PDFs encontrados | 3.316 |
| PDFs indexados | 3.288 (99,2%) |
| — via PyMuPDF | 3.218 |
| — via OCR (Tesseract por+eng, 300 DPI) | 70 |
| PDFs irrecuperáveis | 10 |
| Chunks gerados (LanceDB) | 34.285 |
| Média chunks/doc | 10,4 |

**Store:** Google Drive — `G:/Meu Drive/ufpr_rag/store/ufpr.lance/`
**Tabelas:** `ufpr_docs` (34.623 chunks flat) + `ufpr_raptor` (12 nós hierárquicos)

## Distribuição por Conselho

| Conselho | Atas | Resoluções | Inst. Normativas |
|---|---|---|---|
| CEPE | 731 | 648 | 8 |
| COPLAD | 630 | 474 | 1 |
| COUN | 217 | 435 | 1 |
| CONCUR | 143 | 10 | — |
| Estágio | — | — | 18 (manuais, leis) |

## Irrecuperáveis (10 arquivos)

- **7 vazios** (0 bytes) — lote `ata_cepe_17022014-72{9..36}.pdf` (falha no download original)
- **2 corrompidos** — `concur/atas/ata_concur_{12082015-891,23032015-845}.pdf`
- **1 imagem ilegível**

A lista completa de PDFs originalmente vazios (recuperados depois via OCR) e dos arquivos com erro pode ser obtida via `git show 6326b7f:ufpr_automation/RAG_INGESTION_REPORT.md`.

## Próximos passos

- Re-baixar os 9 arquivos vazios/corrompidos do site da UFPR (fora do escopo atual)
- Re-executar `raptor` se chunks crescerem significativamente
