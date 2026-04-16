# Guia de Navegacao SIGA

Referencia para navegacao Playwright no SIGA (Sistema Integrado de Gestao Academica). Seletores capturados via DOM real (2026-04-15). A automacao e **read-only** — nenhuma operacao de escrita.

---

## 1. Login — Portal de Sistemas (Keycloak SSO)

```
URL:      https://sistemas.ufpr.br
Auth:     Keycloak (input#username, input#password, input#kc-login)
Pos-login: selecionar card "Coordenacao / Secretaria - Graduacao"
Redirect:  https://siga.ufpr.br/siga/selecionanivelacesso?comboAcesso=...
Indicador: presenca de link "Sair" + menu lateral "Discentes"
```

O antigo form direto em `siga.ufpr.br` foi removido. O `auto_login` em `siga/browser.py` lida com o fluxo SSO completo. Credenciais em `.env`: `SIGA_USERNAME`, `SIGA_PASSWORD`.

---

## 2. Menu lateral (sidebar)

| Menu | Submenu | URL interna | Descricao |
|---|---|---|---|
| Inicio | — | /siga/ | Dashboard: quadro geral, equipe, calendario |
| **Discentes** | **Consultar** | /siga/discente?operacao=listar | Lista de discentes (busca por GRR/nome/doc) |
| | Gerenciar Matriculas | /siga/graduacao/matricula/ajuste | Mobilidade academica |
| | Trancamentos de Curso | /siga/graduacao/trancamentos.jsp | Solicitacoes trancamento/destrancamento |
| | Confirmacao de vaga | /siga/graduacao/discente?op=listaCandidatosMatricula | Candidatos aguardando vaga |
| | Gerenciar Matriculas Eletivas | /siga/graduacao/matriculaEletiva | Disciplinas eletivas |
| | Cancelamentos de Turmas | /siga/graduacao/solicitacoesCancelamentoTurma | |
| | Comprovantes de Vacinacao | — | |
| Docentes | Consultar | /siga/docente?operacao=listar | 11 internos, 0 externos |
| Disciplinas | Ofertar Turmas | /siga/turmasGraduacao?op=ofertar | Periodo PROGRAD |
| | Relatorio | /siga/turmasGraduacao?op=relatorio | Alunos-Solicitacoes, Matriculados |
| Contato | — | — | |
| Exames | — | /siga/graduacao/exames | Aproveitamento e adiantamento |
| Equivalencias | — | /siga/graduacao/equivalencias | |
| Relatorios | Dinamico de Discentes | /siga/graduacao/relatoriodinamico | CSV/Excel export |
| | Integralizacao | — | |
| Colacoes de Grau | — | /siga/graduacao/colacoes?op=listar | |
| Analise de Abandono | — | /siga/graduacao/abandono | |
| Estagio Periodo Especial | Indicar / Listar | /siga/graduacao/estagioPeriodoEspecial | |
| Indicadores Academicos | — | — | Filtro ano ingresso, abas Disciplinas/Ofertas |

---

## 3. Perfil do discente — Abas

Acesso: `Discentes > Consultar > clicar no nome do aluno`

Cada aba e um `<div class="tab-pane" id="tab_{nome}">`. O conteudo carrega via AJAX (Vue.js) — aguardar "Carregando..." desaparecer antes de ler o DOM.

| Aba | Pane ID | Seletor do tab | Conteudo-chave |
|---|---|---|---|
| Informacoes Gerais | `tab_informacoes` | `a:has-text('Informacoes Gerais')` | Status, Data Matricula, Emails, CPF |
| Dados Complementares | `tab_dadoscomplementares` | `a:has-text('Dados Complementares')` | |
| Curriculos | `tab_curriculos` | `a:has-text('Curriculos')` | Forma ingresso/evasao |
| **Historico** | `tab_historico` | `a:has-text('Historico')` | IRA, disciplinas/semestre, Situacao |
| **Integralizacao** | `tab_integralizacao` | `a:has-text('Integralizacao')` | CH summary, disciplinas Vencida/Nao Vencida |
| Grade Horaria | `tab_gradehoraria` | `a:has-text('Grade Horaria')` | |
| Atividades Formativas | `tab_atividadesformativas` | `a:has-text('Atividades Formativas')` | |
| Componentes Flexiveis | `tab_componentesflexiveis` | `a:has-text('Componentes Flexiveis')` | |
| Trancamento | `tab_trancamento` | `a:has-text('Trancamento')` | Solicitacoes do aluno |
| Exames | `tab_exames` | `a:has-text('Exames')` | |
| Equivalencias | `tab_equivalencias` | `a:has-text('Equivalencias')` | |
| Log Historico | `tab_loghistorico` | `a:has-text('Log Historico')` | Acoes no cadastro |
| **Estagio** | `tab_estagio` | `a:has-text('Estagio')` | Estagios vinculados |
| Evasao | `tab_evasao` | `a:has-text('Evasao')` | |
| Desempenho | `tab_desempenho` | `a:has-text('Desempenho')` | |
| Observacoes | `tab_observacoes` | `a:has-text('Observacoes')` | |
| Documentos | `tab_documentos` | `a:has-text('Documentos')` | |
| Documentos Pessoais | `tab_documentospessoais` | `a:has-text('Documentos Pessoais')` | |
| Comprovante de vacinacao | `tab_comprovantevacinacao` | `a:has-text('Comprovante de vacinacao')` | |

---

## 4. Historico — Estrutura DOM

```
#tab_historico
  h2.page-header  "Historico"
  label "Curriculo" + p  → "93B - 2016 - Design Grafico (1333)"
  label "IRA" + p.h4     → "0.3654"
  
  h3  "1o Semestre / 2015"       (repete para cada semestre)
    p  "Carga Horaria Cursada: 390 h"
    p  "IRA: 0.5131"
    table#tabela.table.table-striped
      th: Sigla | Disciplina | Docente | Curric. Atual | Carga Horaria | Nota | Frequencia | Situacao | Obs.
      td[7] (Situacao): "Aprovado" | "Reprovado por Frequencia" | "Reprovado por Nota" | "Reprovado" | "Matriculado"
```

---

## 5. Integralizacao — Estrutura DOM

```
#tab_integralizacao
  h2.page-header  "Integralizacao"
  label "Curriculo" + p
  label "CH Obrigatorias:" + p  → "1920 de 1980 h"
  label "CH Optativas:" + p     → "300 de 300 h"
  label "CH Atividades Formativas:" + p → "0 de 180 h"
  label "CH Total:" + p          → "2220 de 2460 h"
  span.label.label-danger  "Nao integralizado"  (ou label-success "Integralizado")

  h3  "1o Periodo"               (repete para cada periodo curricular)
    p  "Carga Horaria Exigida: 330 h"
    p  "Carga Horaria Vencida: 330 h"
    table#tabela.table.table-striped
      th: Sigla | Disciplina | Carga Horaria | Situacao | Vencida em | Observacoes
      td[3] (Situacao): span.label.label-success "Vencida" | span.label "Nao Vencida"
```

---

## 6. Disciplinas-chave para elegibilidade de estagio

| Sigla | Nome | CH | Significado para estagio |
|---|---|---|---|
| OD501 | Estagio Supervisionado | 360h (anual) | Se "Nao Vencida", aluno tem >= 1 ano de curso |
| ODDA6 | Design Aplicado 6 (TCC1) | 120h | Pre-req TCC2; se "Nao Vencida", >= 1 ano restante |

**Regra**: se vigencia do estagio > 6 meses e nenhuma dessas duas esta pendente, verificar se aluno pode se formar antes do fim da vigencia.

---

## 7. Campo de busca na lista de discentes

```
Seletor: input[placeholder*='Nome ou Documento']
Tipo: text (filtragem client-side, nao requer submit)
Aceita: GRR (sem prefixo), nome parcial, CPF
```

---

## 8. Fluxo de Verificacao de Estagios

```
Receber email com TCE
  |
  v
SIGA: Discentes > Consultar > buscar por GRR
  |
  v
Aba "Informacoes Gerais": verificar Status = "Registro ativo"
  |
  v
Aba "Historico": contar reprovacoes
  |-- > 2 reprovacoes total → SOFT BLOCK: solicitar justificativa
  |
  v
Aba "Integralizacao":
  |-- curriculo "Integralizado" → HARD BLOCK: nao pode estagiar
  |-- OD501 ou ODDA6 pendente → aluno tem >= 1 ano, OK para estagio 12m
  |-- poucas disciplinas restantes, sem OD501/ODDA6 → WARN: pode formar antes do fim
  |
  v
→ continua no SEI (ver NAVEGACAO_SEI.md)
```

---

## 9. Manifest de Seletores

| Arquivo | Producao | Validacao |
|---|---|---|
| `procedures_data/siga_capture/latest/siga_selectors.yaml` | `scripts/siga_capture_estagios.py` + grounder | `siga/selectors.py` (forbidden guard) |

Carrega lazily, valida contra `_FORBIDDEN_SELECTORS` no load, consumido por `siga/client.py`.

---

## 10. Notas Tecnicas

- **Vue.js SPA**: abas carregam conteudo via AJAX. Usar `_wait_tab_content(page, pane_id)` antes de ler DOM.
- **Sessao**: `_session_browser.py` persiste `storage_state` em `session_data/siga_state.json`. Em steady-state, logins sao reaproveitados.
- **IDs internos**: o SIGA usa IDs internos para discentes (ex: `d=71277`), diferentes do GRR. Sempre buscar por GRR/nome.
- **Periodos PROGRAD**: varias funcionalidades (Ofertar Turmas, Analise de Abandono) ficam bloqueadas fora dos periodos definidos pelo calendario da PROGRAD.
