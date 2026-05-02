# COMPLETED_TASKS — histórico de conclusões

Este arquivo agrega seções "✅ Concluído" que foram movidas de [TASKS.md](TASKS.md)
pra reduzir o ruído no roadmap atual. Para histórico ainda mais antigo
(Marcos I/II/II.5/III), consulte `git log` ou versões anteriores de TASKS.md.

---

### ✅ Concluído (2026-04-22) — Checker supervisor + cascade AE por nome + end-to-end Marlon

**Checker novo `supervisor_formacao_compativel`** (SOFT, 16º checker registrado):
- Regra: Art. 9 Lei 11.788/2008 + Art. 10 Res. CEPE 46/10 — supervisor precisa ter formação/experiência em área afim ao curso. Se NÃO tiver → exigir **Declaração de Experiência do Supervisor** (form PROGRAD `http://www.prograd.ufpr.br/estagio/formularios/form/declaracao_experiencia.php` assinado pela chefia imediata).
- Extração: `_SUPERVISOR_NOME_RE` + `_SUPERVISOR_FORMACAO_RE` em `procedures/playbook.py` (labels "Supervisor:", "Formação do Supervisor:", "Cargo do Supervisor:", etc.).
- Lista curada `_SUPERVISOR_AREAS_AFINS_DESIGN` em `checkers.py` (~28 áreas afins ao Design Gráfico, derivadas de `GUIA_ESTAGIOS_DG.txt` §SUPERVISOR + SOUL.md §7). Normalização accent-insensitive + case-insensitive.
- Comportamento: pass silencioso quando `formacao_supervisor` não foi extraída (outros checkers cuidam de TCE incompleto). Soft_block com mensagem completa (link do form + base legal) quando dado extraído mas fora das áreas afins.
- Entry nova em `SEI_DOC_CATALOG.yaml`: "Declaração de Experiência do Supervisor" (Externo/Declaração/Inicial/sigiloso).
- Registrado em `blocking_checks` do intent `estagio_nao_obrig_acuse_inicial`. **Testes: 11 novos** (3 extract_variables + 8 checker — pass/soft_block/accent-insensitive/missing-data).

**Cascade AE também por nome** (commit `392b063`):
- Após AE-GRR retornar 0 hits → tenta AE com cada candidato de nome extraído do email/anexos, tanto completo quanto curto (first+last).
- `extract_candidate_names(text)` + `shorten_name_first_last(name)` em `sei/client.py`. Filtro por token institucional (UNIVERSIDADE, SETOR, DESIGN, CURSO, etc.) pra evitar falsos positivos.
- Motivação validada live: smoke de `GRR20215550` (MATHEUS KLEINE ALBERS) retornou 0 em AE-GRR mas o AE tem o processo indexado como "Matheus Albers" (só nome).
- Testes: +13 (7 extract + 6 shorten).

**Keywords novas no intent `estagio_nao_obrig_acuse_inicial`**: adicionadas "Termo de Estágio", "Termo de Estágio para assinatura", "assinar TCE", "assinatura do termo", "assinar termo de estágio" — capturam formas curtas usadas pelo aluno (validado live no email do Marlon 2026-04-22 15:55).

**Smoke live Marlon (2026-04-22 15:55)**:
- Email "Termo de Estágio para assinatura" (GRR20223876, anexo PDF 104KB) → **Tier 0 HIT keyword 1.00** `estagio_nao_obrig_acuse_inicial`.
- AE busca por GRR → **1 processo** encontrado direto (`23075.011886/2026-96` — processo ativo em AE do unit).
- `agir_estagios` rodou 16 checkers → HARD BLOCK em `tce_jornada_sem_horario` (TCE não especifica horário da jornada — comportamento correto).
- Rascunho de recusa gerado com a mensagem formal do bloqueador (link do form PROGRAD + reason legal) pra `marloncrybb@gmail.com` CC `design.grafico@ufpr.br`. **NÃO** mais o "vou verificar" genérico do path legacy Marco I.

### ✅ Concluído (2026-04-22) — SEI busca via Acompanhamento Especial (AE)

Cascade em 4 níveis — os 3 primeiros implementados e validados ao vivo:

| # | Método | Status | Nota |
|---|---|---|---|
| 1 | Nº SEI explícito (`23075.*`) | ✅ `extract_sei_process_number` + `search_process` | UFPR prefix-only |
| **2** | **AE + palavra-chave** | ✅ **validado ao vivo 2026-04-22** | `#txtPalavrasPesquisaAcompanhamento` + `#tblAcompanhamentos` (8 colunas) |
| 3 | Pesquisa Rápida geral por GRR | ✅ `find_processes_by_grr` + `_parse_search_results_table` (`table.pesquisaResultado`) | Fallback quando AE retorna 0 |
| 4 | Pesquisa Rápida geral por nome | ⏳ trivial (mesmo `#txtPesquisaRapida` com nome) | Risco de homônimos |

**O que foi feito**:
- [x] Captura ao vivo via `scripts/sei_drive.py --target ae_keyword_search` (novo target): identificou selectors `#txtPalavrasPesquisaAcompanhamento` (input) e `#tblAcompanhamentos` (tabela, 8 colunas: checkbox, sort, Processo, Usuário, Data, Grupo, Observação, Ações). Captura em `procedures_data/sei_capture/20260422_143854/raw/`.
- [x] `SEIClient.find_in_acompanhamento_especial(keyword)` + `_parse_ae_results_table()` em `sei/client.py`. Regex restrito a UFPR (`23075.*`) também no parser AE.
- [x] Cascade em `graph/nodes.py:_consult_sei_async` (batch node) **E** em `_consult_sei_for_email` (Fleet single-email path — o que realmente roda em produção). Ordem: nº SEI → AE GRR → Pesquisa Rápida GRR → select_best_processo. `lookup_mode` vira `"ae"` quando AE resolveu.
- [x] 6 testes novos em `test_sei.py` (parser + fluxo completo + edge cases IFPR/menu ausente).
- [x] **Smoke live 2026-04-22 14:59**: email "Re: Contrato CIEE" (Estágios, GRR20215550) → `SEI: busca AE por palavra-chave 'GRR20215550'` → 0 hits em AE → fallback automático pra Pesquisa Rápida → 7 processos retornados → select_best_processo desambiguou. Cascade completo exercitado.

**Observação**: GRR20215550 (MATHEUS KLEINE ALBERS) não está no AE desse unit porque o processo dele é antigo. Para alunos com processo ativo marcado em AE (exemplo validado no smoke do dia: GRR20223876 MARLON), AE retorna 1 match direto e pula a Pesquisa Rápida.
