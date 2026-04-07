# Relatório de Ingestão RAG

**Data:** 2026-04-07
**Branch:** `feat/marco-i-unified`
**Comando:** `python -m ufpr_automation.rag.ingest`

---

## Resumo Geral

| Métrica             | Valor   |
|---------------------|---------|
| PDFs encontrados    | 3.316   |
| PDFs indexados      | 3.218   |
| PDFs vazios (empty) | 71      |
| PDFs com erro       | 9       |
| Não processados     | 18 (*)  |
| Chunks gerados      | 33.881  |
| Média chunks/doc    | 10,5    |

(*) O script reporta `skipped: 18` — são documentos ignorados por lógica interna (possivelmente duplicados ou já existentes no índice).

---

## Distribuição por Conselho e Tipo

| Conselho | Tipo        | PDFs | Observação |
|----------|-------------|------|------------|
| CEPE     | atas        | 731  | Atas do Conselho de Ensino, Pesquisa e Extensão |
| CEPE     | resoluções  | 648  | Resoluções normativas CEPE |
| CEPE     | instruções  | 8    | Instruções normativas CEPE |
| COPLAD   | atas        | 630  | Atas do Conselho de Planejamento e Administração |
| COPLAD   | resoluções  | 474  | Resoluções normativas COPLAD |
| COPLAD   | instruções  | 1    | Instruções normativas COPLAD |
| COUN     | resoluções  | 435  | Resoluções do Conselho Universitário |
| COUN     | atas        | 217  | Atas do Conselho Universitário |
| COUN     | instruções  | 1    | Instruções normativas COUN |
| CONCUR   | atas        | 143  | Atas do Conselho de Curadores |
| CONCUR   | resoluções  | 10   | Resoluções CONCUR |
| **Total**|             | **3.298** | *18 docs de subsets adicionais (estágio, etc.)* |

---

## Documentos Vazios (71 PDFs — sem texto extraível)

PDFs que o PyMuPDF abriu com sucesso mas não extraiu nenhum texto. Provavelmente são **documentos escaneados** (imagens) que precisariam de OCR, ou PDFs que contêm apenas imagens/assinaturas digitais.

### CEPE — Atas (22)

| Arquivo | Provável causa |
|---------|----------------|
| `cepe/atas/Ata-2a-Camara-do-CEPE-14.03.2024.pdf` | Escaneado |
| `cepe/atas/Ata-2ª-CEPE-11.11.2021.pdf` | Escaneado |
| `cepe/atas/Ata-da-Sessão-da-3ª-Câmara-do-CEPE-17.10.2017.pdf` | Escaneado |
| `cepe/atas/Ata-Sessao-2a-Camara-do-CEPE-13.03.25.pdf` | Escaneado |
| `cepe/atas/ata_cepe_05102007-158.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_06122007-166.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_06122007-167.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_07032008-45.pdf` | Escaneado (2008) |
| `cepe/atas/ata_cepe_07122007-160.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_08112007-159.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_11092007-157.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_17082007-156.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_18112014-814.pdf` | Escaneado (2014) |
| `cepe/atas/ata_cepe_19022008-168.pdf` | Escaneado (2008) |
| `cepe/atas/ata_cepe_22022008-161.pdf` | Escaneado (2008) |
| `cepe/atas/ata_cepe_24032009-233.pdf` | Escaneado (2009) |
| `cepe/atas/ata_cepe_24042007-163.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_24082007-164.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_25092007-165.pdf` | Escaneado (2007) |
| `cepe/atas/ata_cepe_27022007-162.pdf` | Escaneado (2007) |
| `cepe/atas/Ata_de_homologacao_das_inscricoes-Comissão-eleitoral.pdf` | Escaneado |
| `cepe/atas/Resultado_Eleicoes_Representacao_Docente_COPLAD_e_CEPE.pdf` | Escaneado |

### CEPE — Resoluções (10)

| Arquivo | Provável causa |
|---------|----------------|
| `cepe/resolucoes/Atividades-acadêmicas-UAB.pdf` | Escaneado |
| `cepe/resolucoes/cepe-34_17-CEPE.assinada_corrigida.pdf` | Assinatura digital (2017) |
| `cepe/resolucoes/cepe3317assinada.pdf` | Assinatura digital (2017) |
| `cepe/resolucoes/cepe3517assinada.pdf` | Assinatura digital (2017) |
| `cepe/resolucoes/cepe3617assinada.pdf` | Assinatura digital (2017) |
| `cepe/resolucoes/cepe3717assinada.pdf` | Assinatura digital (2017) |
| `cepe/resolucoes/Res.-08-18-CEPE-elenco-Depto-Anatomia.pdf` | Escaneado (2018) |
| `cepe/resolucoes/resolucao_cepe_11092014-925.pdf` | Escaneado (2014) |
| `cepe/resolucoes/resolucao_cepe_11092014-926.pdf` | Escaneado (2014) |
| `cepe/resolucoes/Resolução-18-18-CEPE-assinada.pdf` | Assinatura digital (2018) |

### CONCUR — Atas (12)

| Arquivo | Provável causa |
|---------|----------------|
| `concur/atas/Ata-apuração-2017.pdf` | Escaneado |
| `concur/atas/Ata-CONCUR-08.03.17.pdf` | Escaneado (2017) |
| `concur/atas/Ata-CONCUR-12.04.17.pdf` | Escaneado (2017) |
| `concur/atas/Ata-CONCUR-15.03.17-1.pdf` | Escaneado (2017) |
| `concur/atas/Ata-CONCUR-22.02.17-1.pdf` | Escaneado (2017) |
| `concur/atas/Ata-CONCUR-dia-18.05.21-assinada.pdf` | Assinatura digital (2021) |
| `concur/atas/Ata-Sessão-10.08.2016.pdf` | Escaneado (2016) |
| `concur/atas/Ata-Sessão-14.09.2016.pdf` | Escaneado (2016) |
| `concur/atas/Ata-Sessão-19.10.2016.pdf` | Escaneado (2016) |
| `concur/atas/Ata-Sessão-23.11.2016.pdf` | Escaneado (2016) |
| `concur/atas/Ata-Sessão-25.05.2016.pdf` | Escaneado (2016) |
| `concur/atas/Ata-sessão-CONCUR-21.12.2016.pdf` | Escaneado (2016) |

### CONCUR — Resoluções (2)

| Arquivo | Provável causa |
|---------|----------------|
| `concur/resolucoes/Resolução-01.18-CONCUR-Aprovação-R.G.-2017.pdf` | Escaneado |
| `concur/resolucoes/Resolução-nº-01.17-CONCUR.pdf` | Escaneado (2017) |

### COPLAD — Atas (8)

| Arquivo | Provável causa |
|---------|----------------|
| `coplad/atas/ata_coplad_01102009-303.pdf` | Escaneado (2009) |
| `coplad/atas/ata_coplad_05032008-192.pdf` | Escaneado (2008) |
| `coplad/atas/ata_coplad_08032007-177.pdf` | Escaneado (2007) |
| `coplad/atas/ata_coplad_09082007-172.pdf` | Escaneado (2007) |
| `coplad/atas/ata_coplad_12042007-176.pdf` | Escaneado (2007) |
| `coplad/atas/ata_coplad_28112007-193.pdf` | Escaneado (2007) |
| `coplad/atas/Ata_de_homologacao_das_inscricoes-Comissão-eleitoral.pdf` | Escaneado |
| `coplad/atas/Resultado_Eleicoes_Representacao_Docente_COPLAD_e_CEPE.pdf` | Escaneado |

### COPLAD — Resoluções (7)

| Arquivo | Provável causa |
|---------|----------------|
| `coplad/resolucoes/coplad3717-com-assinatura.pdf` | Assinatura digital (2017) |
| `coplad/resolucoes/coplad3817-com-assinatura.pdf` | Assinatura digital (2017) |
| `coplad/resolucoes/coplad3917-com-assinatura.pdf` | Assinatura digital (2017) |
| `coplad/resolucoes/coplad4017-com-assinatura.pdf` | Assinatura digital (2017) |
| `coplad/resolucoes/coplad6895.pdf` | Escaneado (1995) |
| `coplad/resolucoes/Resolucao-no-20-25-COPLAD.pdf` | Escaneado |
| `coplad/resolucoes/RESOLUÇÃO-Nº-14-23-COPLAD-1.pdf` | Escaneado (2023) |

### COUN — Atas (2)

| Arquivo | Provável causa |
|---------|----------------|
| `coun/atas/Ata-Colégio-Eleitoral-Reitor-06-10-2016.pdf` | Escaneado (2016) |
| `coun/atas/Colegio_Eleitoral___Ata_27_09_2024-1.pdf` | Escaneado (2024) |

### COUN — Resoluções (8)

| Arquivo | Provável causa |
|---------|----------------|
| `coun/resolucoes/Ad-referendum-vigência-Res.-01-22-Covid-19.pdf` | Escaneado |
| `coun/resolucoes/coun0187.pdf` | Escaneado (1987) |
| `coun/resolucoes/coun0918-Assinada.pdf` | Assinatura digital (2018) |
| `coun/resolucoes/Res.-18-17.pdf` | Escaneado (2017) |
| `coun/resolucoes/Res.-23-17-COUN-assinada.pdf` | Assinatura digital (2017) |
| `coun/resolucoes/resolucao_coun_18092014-929.pdf` | Escaneado (2014) |
| `coun/resolucoes/RESOLUÇÃO-N-º-15-23-COUN.pdf` | Escaneado (2023) |
| `coun/resolucoes/RESOLUÇÃO-Nº-14-23-COUN-1.pdf` | Escaneado (2023) |

---

## Documentos com Erro (9 PDFs — falha ao abrir)

Esses PDFs falharam na abertura pelo PyMuPDF. São arquivos **vazios (0 bytes)** ou **corrompidos**.

### Arquivos vazios (Cannot open empty file) — 7

Todos do mesmo lote (`ata_cepe_17022014-*`), sugerindo falha no download original:

| Arquivo |
|---------|
| `cepe/atas/ata_cepe_17022014-729.pdf` |
| `cepe/atas/ata_cepe_17022014-731.pdf` |
| `cepe/atas/ata_cepe_17022014-732.pdf` |
| `cepe/atas/ata_cepe_17022014-733.pdf` |
| `cepe/atas/ata_cepe_17022014-734.pdf` |
| `cepe/atas/ata_cepe_17022014-735.pdf` |
| `cepe/atas/ata_cepe_17022014-736.pdf` |

### Arquivos corrompidos (Failed to open file) — 2

| Arquivo |
|---------|
| `concur/atas/ata_concur_12082015-891.pdf` |
| `concur/atas/ata_concur_23032015-845.pdf` |

---

## Análise e Recomendações

### Cobertura
- **97,6%** dos PDFs foram indexados com sucesso (3.218 / 3.298 dos conselhos)
- A base de conhecimento cobre **4 conselhos** (CEPE, COPLAD, COUN, CONCUR) com **atas, resoluções e instruções**
- Período coberto: **~1987 a 2026**

### Documentos vazios — potencial de recuperação via OCR
- 71 PDFs são provavelmente **escaneados** (imagens de documentos)
- A maioria são de **2007-2009** (atas antigas digitalizadas) e **2016-2017** (atas CONCUR)
- Com Tesseract OCR instalado, o módulo `attachments/extractor.py` já suporta OCR
- **Recomendação:** rodar re-ingestão com OCR habilitado para recuperar ~71 documentos adicionais

### Documentos com erro — re-download necessário
- 7 PDFs do CEPE (lote `17022014-*`) estão com **0 bytes** — falha no download
- 2 PDFs do CONCUR estão **corrompidos**
- **Recomendação:** re-baixar esses 9 arquivos do site da UFPR e re-ingerir

### Próximo passo
- Construir a árvore RAPTOR (`python -m ufpr_automation.rag.raptor`) sobre os 33.881 chunks indexados
