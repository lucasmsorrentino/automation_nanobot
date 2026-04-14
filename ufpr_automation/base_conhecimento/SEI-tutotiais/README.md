# SEI-tutotiais — Base de conhecimento operacional do SEI UFPR

60 POPs (Procedimentos Operacionais Padrão) oficiais do SEI UFPR + PVA + Novidades SEI 4.0.0 + organograma.

## Propósito

1. **Enriquecer o Tier 0 atual** (Estágios — TCE/Aditivo/Rescisão) com detalhamento operacional do fluxo SEI.
2. **Base de conhecimento para agente chat-driven full-SEI**: operações SEI sob demanda via chat. **Política atual (Marco IV)**: `_FORBIDDEN_SELECTORS` bloqueia assinar/protocolar/enviar processo — POPs desses fluxos (POP-22/32/51/52/54) entram no RAG com `write_forbidden=true` e são apenas *explicados*. **Marco futuro**: execução desses fluxos está planejada; o boundary existe hoje para blindar alucinações de LLM durante maturação e manter human-in-the-loop, não como veto permanente.
3. **Auditoria de selectors** (`sei/sei_selectors.yaml`) — os POPs descrevem os campos, dropdowns e confirmações esperados na UI.

## Guia visual rápido do fluxo TCE (apoio, não normativo)

`G:\Meu Drive\ufpr_rag\docs\estagio\manual-de-estagios-versao-final.pdf` — páginas impressas **81–83** (PDF pgs 41–42), anexo "Como tramitar a documentação de estágios via SEI". Dá uma ideia rápida com screenshots do fluxo que já foi executado com sucesso no processo `23075.020970/2026-09`; para detalhamento operacional completo, usar os POPs (especialmente POP-5 e POP-25).

Passo a passo resumido:

1. Iniciar Processo (tipo de processo de estágio)
2. Especificações = NOME DO CURSO; Interessados = NOME DO ALUNO + MATRÍCULA; Salvar
3. Anotar nº do processo no TCE, digitalizar em PDF (se origem não for digital)
4. Incluir Documento → Externo
5. Tipo; Data; Tipo de Conferência (**ver regra abaixo**); Escolher Arquivo; Confirmar Dados
6. Enviar Processo → **UFPR/R/PROGRAD/CGE** (hoje: passo humano — não automatizado por enquanto)

## Regra de `Tipo de Documento` + `Nome na Árvore` (TCE e afins)

Ambos são apenas rótulos visuais — não têm efeito legal. Estratégia:

1. Tentar `Termo` no dropdown. Se achar → `Nome na Árvore = "Compromisso de Estágio"`.
2. Fallback: `Documento` → `Nome na Árvore = "Termo de Compromisso"` ou `"TCE"`.

Vale a mesma lógica para Aditivo, Rescisão, Relatório Final, Ficha de Avaliação. Não bloquear o fluxo por causa deste campo.

## Regra de `tipo_conferencia`

| Origem do documento | Valor `tipo_conferencia` |
|---------------------|--------------------------|
| Digital nativo (PDF gerado direto, assinado eletronicamente, recebido por e-mail) | `Nato Digital` |
| Escaneado / OCR (papel físico digitalizado) | `Cópia Autenticada Administrativamente` |

Heurística automática no `attach_document`: se o PDF passou por OCR (branch `needs_ocr=true` do `attachments/extractor.py`), usar `Cópia Autenticada Administrativamente`; caso contrário, `Nato Digital`.

## Triagem A/B/C

### Bucket A — CRITICAL para Tier 0 atual (Estágios)

Mapeiam diretamente aos 3 métodos do `SEIWriter` (`create_process`, `attach_document`, `save_despacho_draft`).

POPs canônicos do fluxo **Estágio não obrigatório** (confirmado pelo Lucas 2026-04-14):

| POP | Título | Mapeia para |
|-----|--------|-------------|
| POP-5 | Iniciar Processo | `create_process` |
| POP-25 | Incluir documento externo | `attach_document` (TCE / PDF) |
| POP-19 | Criar documento interno | `save_despacho_draft` (despacho) |
| POP-20 | Editar documento interno | Body do `save_despacho_draft` (editor WYSIWYG) |
| POP-38 | Incluir processo em Acompanhamento Especial | `add_to_acompanhamento_especial` (novo) — grupo `"Estágio não obrigatório"` |

POP auxiliar (não no fluxo principal, mas útil como referência):

| POP | Título | Mapeia para |
|-----|--------|-------------|
| POP-26 | Excluir documento do processo | Rollback em caso de upload errado |

POP-21 (Gerar versão do documento) — movido pra Bucket C: pouca relevância pro Tier 0 atual (Lucas confirmou 2026-04-14).

### Bucket B — NEAR-TERM (expansão Acadêmico / Diplomação / Requerimentos)

Ainda no lado *write*, mas fora do escopo Estágios atual.

| POP | Título | Uso previsto |
|-----|--------|--------------|
| POP-2 | Receber processo | Pré-condição para agir |
| POP-3 | Atribuir processo | Distribuição de carga |
| POP-15 | Enviar processo | **Não por enquanto** — humano executa; automação prevista em marco futuro |
| POP-16 | Concluir processo | Fechamento após despacho final |
| POP-23 | Criar texto padrão | Templates de despacho reutilizáveis |
| POP-24 | Criar/alterar modelo de documento | Mapeia a `graphrag.templates.TemplateRegistry` |
| POP-28 | Incluir doc em múltiplos processos | Avisos recorrentes |
| POP-30 | Dar ciência | Frequente em Acadêmico |
| POP-31 | Encaminhar doc p/ assinatura em outra Unidade | Diplomação |
| POP-43 | Executar pesquisa | Lookup de processos referenciados |
| POP-44 | Reabrir processo | Recuperação |
| POP-48 | Enviar e-mail via SEI | Notificações oficiais |
| POP-7, POP-9 | Relacionar / Iniciar processo relacionado | Aproveitamento / Equivalência |

### Bucket C — FUTURE / full-SEI chat agent

Operações avançadas, ingerir no RAG para o chat agent responder "como faço X?" — a maior parte é read-side ou organizacional.

- **Navegação/gestão**: POP-1 (Acessar), POP-4 (Anotação), POP-21 (Gerar versão do documento), POP-6 (Excluir processo), POP-8 (Remover relacionamento), POP-10/11 (Anexar/Abrir anexado), POP-12/13 (Sobrestar/Remover), POP-14 (Duplicar), POP-17/18 (Pontos de controle), POP-27 (Cancelar doc), POP-29 (Imprimir), POP-33 (Encaminhar p/ consulta), POP-37 (Histórico), POP-39/40 (Alterar/Excluir grupo de Acompanhamento Especial — POP-38 moveu pra Bucket A), POP-53 (Marcadores), POP-55 (Filtro), POP-56 (Pesquisar no processo), POP-57 (Comparação versões).
- **Blocos e BoC**: POP-34–36 (Blocos Reunião/Interno), POP-41/42 (Base de Conhecimento).
- **Export/estatística**: POP-45/46 (Export PDF/ZIP), POP-47 (Estatística), PVA-INSTRUÇÕES.
- **Comunicação**: POP-49 (Grupo email), POP-50 (Visualização externa).
- **Novidades**: Novidades_SEI_4.0.0.pdf — mudanças da v4 (impacta selectors).

### Write-forbidden hoje (ingerir no RAG com `write_forbidden=true`)

O agente hoje pode **explicar** esses fluxos mas não executar — boundary blinda alucinação de LLM e mantém human-in-the-loop durante a maturação. **Em marcos futuros** esses fluxos serão executados pela automação (não é veto permanente).

| POP | Título | Por que forbidden |
|-----|--------|-------------------|
| POP-22 | Assinar documento interno | Efeito legal de assinatura |
| POP-32 | Assinar documento encaminhado por outra Unidade | idem |
| POP-51, POP-52 | Cadastrar/solicitar assinatura externa | Cadeia de assinatura |
| POP-54 | Bloco de Assinatura | Batch de assinaturas |
| POP-58 | Administração de sigilosos | Sensível — manual |

## Ingestão RAG

Subset `sei_pop` (opt-in):

```bash
python -m ufpr_automation.rag.ingest --subset sei_pop
```

Metadata esperado por chunk: `conselho=sei`, `tipo=pop`, `pop_numero`, `bucket` (A|B|C|forbidden), `write_forbidden` (bool).

## Staging de docs pendentes de ingestão

Backlog centralizado em `G:\Meu Drive\ufpr_rag\docs\ainda_n_ingeridos\` — PDFs, HTMLs, dumps UFPR Aberta, POPs novos, resoluções CEPE/CONSUN, manuais atualizados, etc. ainda não processados pelo `rag/ingest.py`. Antes de concluir que "o doc X não está na base", consultar lá. Ao ingerir, mover para a subpasta definitiva do subset correspondente.

## Cross-check com `sei_selectors.yaml`

Antes do próximo live e2e (Sprint 3), confirmar cobertura dos campos destacados nos POPs A:

- **POP-5**: tipo_processo picker, interessado autocomplete, observacoes textarea, nivel_acesso radio (Público/Restrito/Sigiloso) + hipotese_legal + grau_sigilo condicionais, salvar.
- **POP-25**: btnIncluirDoc, tipo_documento, data_documento (calendar), numero_nome_arvore, **tipo_conferencia** (dropdown, fácil de esquecer), remetente + interessados autocompletes, file input, confirmar.
- **POP-19**: btnIncluirDoc, tipo_doc list, texto_inicial radio (Nenhum/Modelo/Padrão), descricao, interessados, destinatarios, observacoes, confirmar_dados.
- **POP-20**: editar_conteudo, editor iframe (seções de fundo branco editáveis), salvar.
- **POP-38**: ícone "Acompanhamento Especial" (estrela/marcador) na toolbar do processo, dropdown `Grupo` (selecionar grupo existente OU botão "Novo Grupo" → nome), textarea `Descrição` (breve info do processo), salvar. Restrição: cada processo em apenas 1 grupo. Grupo canônico para estágio não obrigatório: `"Estágio não obrigatório"`.
