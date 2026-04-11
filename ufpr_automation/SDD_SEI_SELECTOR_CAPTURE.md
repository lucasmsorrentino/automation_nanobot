# SDD — Captura de Seletores SEI (Marco IV / Unblock)

> **Status:** pronto para execução  
> **Sprint estimado:** 1 sessão (~30-60 min interativo + revisão)  
> **Bloqueia:** Marco IV — Estágios end-to-end (`SEI_WRITE_MODE=live`)  
> **Custo:** zero (Claude Code rodando sob plano Max)  
> **Pré-requisito humano:** SEI de teste OU autorização para criar processo fictício em produção

---

## 1. Contexto e objetivo

Marco IV (Estágios end-to-end) está com a infra lógica completa — `Intent` model estendido, `SEI_DOC_CATALOG.yaml`, registry de 11 checkers, `SEIWriter` com `create_process` + `attach_document` + `save_despacho_draft` em modo dry-run. **O bloqueio é único:** três `NotImplementedError` em `sei/writer.py` que correspondem ao "live mode" das três operações de escrita. Cada um precisa de um fluxo Playwright determinístico contra os formulários reais do SEI, e os seletores DOM precisam ser capturados de uma sessão SEI ao vivo (não dá pra adivinhar — SEI é legado, IDs são instáveis, alguns elementos só aparecem condicionalmente).

**Objetivo desta sprint:** rodar Claude Code (autenticado com plano Max, sem chave de API) dentro do diretório do projeto, dirigir Playwright em modo headed contra um SEI de teste, navegar os 3 formulários alvo, capturar DOM + screenshots + seletores propostos, e produzir um manifesto YAML que eu uso na sessão seguinte para preencher os 3 stubs do `SEIWriter` com código Playwright determinístico.

**Entrega final:**

1. `procedures_data/sei_capture/<timestamp>/` — diretório com DOM dumps, screenshots, e o manifesto
2. `procedures_data/sei_capture/<timestamp>/sei_selectors.yaml` — o manifesto canônico (schema na §5)
3. Análise de Claude Code propondo seletores Playwright para cada campo
4. (Sessão seguinte) commit no `sei/writer.py` substituindo os 3 `NotImplementedError`
5. (Sessão seguinte) smoke test em `SEI_WRITE_MODE=dry_run` validando o wiring + smoke test em `SEI_WRITE_MODE=live` contra processo de teste

---

## 2. Restrições e princípios de safety

| Restrição | Razão |
|---|---|
| **Plano Max, sem chave de API Anthropic** | Custo zero. Claude Code CLI usa quota da assinatura. Não importar `claude-agent-sdk` em código Python. |
| **Sem computer use** | Plano Max não inclui. Playwright é dirigido via Bash tool do Claude Code. |
| **NUNCA clicar em Assinar / Enviar Processo / Protocolar / Tramitar** | Mesma fronteira do `SEIWriter._FORBIDDEN_SELECTORS`. A sessão de captura é READ-ONLY exceto pelos cliques essenciais para abrir os formulários e fechar (sem salvar). |
| **NUNCA salvar processo/documento de verdade nesta sessão** | Captura é só leitura de DOM. Após mapear os seletores, FECHAR o formulário sem salvar (botão Cancelar / Esc / fechar a janela). |
| **Sessão deve rodar em SEI de teste OU em ambiente onde a criação de um processo fictício seja autorizada** | Defesa em profundidade — mesmo que algo escape do "não salvar", o estrago é nulo. |
| **Audit trail obrigatório** | Todo passo gera screenshot + DOM dump em `procedures_data/sei_capture/<timestamp>/`. JSONL log opcional. |
| **Sem rede durante a análise** | Após capturar os DOM dumps, a análise dos seletores roda offline (Claude Code lê os arquivos locais). |

---

## 3. Pré-requisitos do ambiente

Antes de rodar a sprint, verificar:

- [ ] `claude` CLI instalado e autenticado: `claude /login` (uma vez)
- [ ] Estar em `C:\Users\trabalho\Documents\automation\nanobotWork\nanobot` (ou equivalente)
- [ ] Branch `dev` com o último commit (`git pull origin dev`)
- [ ] `.venv` ativada
- [ ] Playwright + Chromium instalados: `python -m playwright install chromium`
- [ ] Credenciais no `ufpr_automation/.env`:
  - `SEI_URL=https://sei.ufpr.br/`
  - `SEI_USERNAME=...`
  - `SEI_PASSWORD=...`
- [ ] Decisão: SEI de teste OU processo fictício autorizado — anotar a URL/credenciais separadas se for de teste
- [ ] Um PDF dummy (~1 página, sem dados sensíveis) salvo em `procedures_data/sei_capture/dummy_tce.pdf` — usado SÓ para testar o file picker do navegador, NÃO será salvo no SEI

---

## 4. Formulários alvo

Três formulários do SEI mapeiam para os três métodos de `SEIWriter`. Cada subseção lista os campos que precisam ser capturados, com nome semântico, tipo esperado, e onde o valor virá quando o `SEIWriter` rodar em produção.

### 4.1 Form `iniciar_processo` → `SEIWriter.create_process`

**Como abrir:**
1. Login no SEI
2. Menu lateral esquerdo → "Iniciar Processo" (ou ícone equivalente)

**Campos a mapear:**

| Nome semântico | Tipo esperado | Valor em produção (vem de) |
|---|---|---|
| `tipo_processo` | dropdown ou autocomplete | `intent.sei_process_type` (ex.: "Graduação/Ensino Técnico: Estágios não Obrigatórios") |
| `especificacao` | text input | "Design Gráfico" (nome do curso, hardcoded ou via settings) |
| `interessado` | text input ou autocomplete | `vars["nome_aluno"] + " - GRR" + vars["grr"]` (ex.: "ALANIS ROCHA - GRR20230091") |
| `nivel_acesso_restrito` | radio button | sempre "Restrito" para Estágios (LGPD) |
| `hipotese_legal` | dropdown (aparece após selecionar Restrito) | "Informação Pessoal" |
| `observacoes` | textarea (opcional) | vazio |
| `salvar` | button | clique único — abre a tela do processo recém-criado |

**Indicadores de sucesso:**
- URL muda para algo tipo `controlador.php?acao=arvore_visualizar&...`
- Um número de processo aparece em `infraBarraComandos` ou `divInfraBarraLocalizacao` — esse número é o `processo_id` que deve ser **extraído e retornado** pelo `create_process`
- A árvore de documentos (vazia) aparece à esquerda

**Riscos / atenção:**
- `tipo_processo` pode ser dropdown nativo, autocomplete (jQuery), ou tabela de seleção em modal — descobrir qual e capturar seletor + tipo
- `interessado` pode ter um picker (busca) ao invés de free text — capturar ambos os caminhos
- "Hipótese Legal" só aparece DEPOIS de selecionar Restrito — capturar a sequência de espera/visibilidade

---

### 4.2 Form `incluir_documento_externo` → `SEIWriter.attach_document`

**Como abrir:**
1. Estar dentro de um processo (com a árvore visível)
2. Clicar no ícone "Incluir Documento" (geralmente um botão verde com `+` no topo da árvore, ou um item de menu)
3. Aparece a tela "Gerar Documento" com lista de tipos
4. Selecionar **"Externo"** (na lista, ou via filtro)

**Campos a mapear (após escolher Externo):**

| Nome semântico | Tipo esperado | Valor em produção (vem de) |
|---|---|---|
| `tipo_documento` | dropdown | `classification.sei_subtipo` (ex.: "Termo", "Relatório") |
| `numero` | text input (opcional) | número do TCE / aditivo / relatório |
| `nome_na_arvore` | text input (opcional) | o rótulo curto que aparece na árvore — pode usar `classification.sei_classificacao` (ex.: "Inicial") |
| `data_documento` | date picker (DD/MM/AAAA) | `classification.data_documento` ou hoje |
| `formato` | radio: "Nato-digital" \| "Digitalizado nesta Unidade" | "Digitalizado nesta Unidade" (TCE assinado em papel/PDF) |
| `tipo_conferencia` | dropdown (aparece se Digitalizado) | "Cópia Simples" ou equivalente — confirmar opções |
| `remetente` | text input (opcional) | vazio |
| `interessados` | text/picker | herdado do processo, geralmente já preenchido |
| `classificacao_ccd` | dropdown (auto na maioria dos casos) | deixar default |
| `observacoes` | textarea (opcional) | vazio |
| `nivel_acesso_restrito` | radio | sempre "Restrito" |
| `hipotese_legal` | dropdown | `classification.motivo_sigilo` (default: "Informação Pessoal") |
| `arquivo` | `<input type=file>` | `file_path` passado como argumento |
| `confirmar` ou `salvar` | button | clique único — adiciona o doc à árvore |

**Indicadores de sucesso:**
- Volta para a árvore do processo
- Um novo nó aparece na árvore com o `nome_na_arvore`
- Captar o ID do novo documento (atributo do nó da árvore) — útil para `AttachResult.documento_id` (campo novo a adicionar?)

**Riscos / atenção:**
- O `tipo_documento` (Termo/Relatório) pode estar como sub-classificação após escolher Externo OU como filtro inicial. Capturar o caminho real.
- A combinação **Termo + Inicial/Aditivo/Rescisão** pode ser:
  - Dois selects encadeados (Tipo → Sub-tipo)
  - Um único campo "Nome na Árvore" onde você digita "Termo de Compromisso de Estágio Inicial"
  - Um campo `Tipo` com valores compostos como "Termo - Inicial"
  - Capturar a forma real e atualizar o `SEI_DOC_CATALOG.yaml` se necessário
- O file picker (`<input type=file>`) é nativo do browser — Playwright resolve via `set_input_files()`, não precisa abrir o diálogo
- Anexar dummy PDF apenas para testar — **NÃO clicar Salvar/Confirmar**. Cancelar e fechar o form.

---

### 4.3 Form `incluir_documento_despacho` → `SEIWriter.save_despacho_draft`

**Como abrir:**
1. Mesma sequência: dentro de um processo → "Incluir Documento"
2. Selecionar **"Despacho"** na lista de tipos

**Campos a mapear (form inicial — antes do editor):**

| Nome semântico | Tipo esperado | Valor em produção (vem de) |
|---|---|---|
| `texto_inicial` | radio: "Nenhum" \| "Documento Modelo" \| "Texto Padrão" | "Nenhum" — vamos colar o texto inteiro do `despacho_template` |
| `descricao` | text input (opcional) | rótulo curto, ex.: "Despacho TCE Inicial" |
| `nome_na_arvore` | text input (opcional) | mesmo |
| `interessados` | text/picker | herdado |
| `destinatarios` | text/picker | (geralmente vazio em despacho) |
| `classificacao_ccd` | dropdown auto | deixar default |
| `observacoes` | textarea (opcional) | vazio |
| `nivel_acesso_restrito` | radio | "Restrito" |
| `hipotese_legal` | dropdown | "Informação Pessoal" |
| `confirmar` | button | abre o **editor rich-text** em uma nova janela/iframe |

**Editor rich-text (segunda etapa, atenção especial):**

| Item | Detalhe |
|---|---|
| Como aparece | Geralmente em uma janela popup do browser (`window.open`) ou em um iframe dentro da página principal |
| Tecnologia provável | **TinyMCE** (SEI usa há anos) |
| Como Playwright acessa | `page.frame_locator("iframe#cke_..." )` ou `page.context.pages[-1]` se for popup |
| Como inserir texto | `frame.locator("body").fill(despacho_text)` ou `evaluate("document.body.innerHTML = ...")` |
| Botão Salvar | dentro da toolbar do editor — capturar selector |
| Após Salvar | janela fecha, processo principal mostra o despacho na árvore |

**Riscos / atenção:**
- Iframe vs popup — Playwright trata diferente. Capturar qual é o caso.
- TinyMCE injeta o `<body contenteditable>` dentro do iframe. O clique direto pode falhar — usar `frame.locator("body").click()` antes do `fill()`.
- Capturar o seletor do botão **Salvar** dentro do editor (cuidado: NÃO confundir com Assinar/Enviar do processo principal).
- O `_FORBIDDEN_SELECTORS` deve permanecer ativo nesta etapa: confirmar que o "Salvar" do editor não bate com nenhum token da lista (`assinar`, `enviar`, `protocolar`, `submit`, `btnAssinar`...). **Se bater, ajustar a lista de tokens proibidos para usar substring matching mais específico** (ex.: trocar `submit` por `submitButton` ou `btnEnviarProcesso`).

---

## 5. Schema do output canônico

Após a captura, gerar **um único arquivo YAML** `procedures_data/sei_capture/<timestamp>/sei_selectors.yaml` no schema abaixo. Esse é o input que eu vou consumir na sessão seguinte para escrever o código Playwright em `sei/writer.py`.

```yaml
# sei_selectors.yaml
metadata:
  captured_at: "2026-04-12T10:30:00-03:00"
  sei_version: "..."     # se aparecer em algum canto da página
  captured_by: "claude-code via plano Max"
  base_url: "https://sei.ufpr.br/"
  notes: |
    Capturado contra processo de teste 23075.000XXX/2026-XX.
    Nenhum documento foi salvo de fato — todos os formulários foram cancelados.

forms:
  iniciar_processo:
    nav_path:
      - {action: "click", selector: "a[id*='lnkInfraMenuSistema']"}
      - {action: "click", selector: "a:has-text('Iniciar Processo')"}
    fields:
      tipo_processo:
        type: "select"           # select | autocomplete | modal_picker | text
        selector: "select#selTipoProcedimento"
        sample_value: "Graduação/Ensino Técnico: Estágios não Obrigatórios"
        notes: "É um <select> nativo, ordenado alfabeticamente"
      especificacao:
        type: "text"
        selector: "input#txtDescricao"
        sample_value: "Design Gráfico"
      interessado:
        type: "autocomplete"
        selector: "input#txtInteressado"
        autocomplete_dropdown: "ul.ac_results"
        sample_value: "ALANIS ROCHA - GRR20230091"
        notes: "Datilografar e selecionar do dropdown — não é free text"
      nivel_acesso_restrito:
        type: "radio"
        selector: "input#radNivelAcessoLocalRestrito"
      hipotese_legal:
        type: "select"
        selector: "select#selHipoteseLegal"
        sample_value: "Informação Pessoal (Art. 31 da Lei nº 12.527/2011)"
        visible_after: "nivel_acesso_restrito"
    submit:
      selector: "button#btnSalvar"
      label: "Salvar"
    success_indicator:
      type: "url_pattern"        # url_pattern | element | both
      url_pattern: "controlador.php?acao=procedimento_visualizar"
      processo_id_extractor:
        selector: "div#divInfraBarraLocalizacao a"
        attribute: "text"
        regex: "^\\s*(\\d{5}\\.\\d{6}/\\d{4}-\\d{2})"
    artifacts:
      dom_dump: "iniciar_processo_form.html"
      screenshot: "iniciar_processo_form.png"

  incluir_documento_externo:
    nav_path:
      - {action: "wait_for", selector: "div#divArvore"}
      - {action: "click", selector: "img[title='Incluir Documento']"}
      - {action: "wait_for", selector: "table#tblSeries"}
      - {action: "click", selector: "a:has-text('Externo')"}
    fields:
      tipo_documento:
        type: "select"
        selector: "select#selSerie"
        sample_value: "Termo"
      # ... (continuar pra cada campo)
    submit:
      selector: "button#btnSalvar"
    success_indicator:
      type: "element"
      element: "div#divArvore a:has-text('{nome_na_arvore}')"
    artifacts:
      dom_dump: "incluir_externo_form.html"
      screenshot: "incluir_externo_form.png"

  incluir_documento_despacho:
    nav_path:
      - {action: "click", selector: "img[title='Incluir Documento']"}
      - {action: "click", selector: "a:has-text('Despacho')"}
    fields:
      texto_inicial_nenhum:
        type: "radio"
        selector: "input#radTextoNenhum"
      # ... (continuar)
    submit_form:
      selector: "button#btnConfirmar"
    editor:
      type: "iframe"             # iframe | popup
      iframe_selector: "iframe#cke_txaConteudo"
      body_selector: "body.cke_editable"
      fill_strategy: "frame_locator_fill"
      save_button:
        selector: "a.cke_button__save"
        label: "Salvar"
        guard_check: "PASS"      # PASS | NEEDS_TOKEN_ADJUSTMENT
        # Se NEEDS_TOKEN_ADJUSTMENT, listar qual token de _FORBIDDEN_SELECTORS bate
    success_indicator:
      type: "element"
      element: "div#divArvore a:has-text('Despacho')"
    artifacts:
      dom_dump_form: "despacho_form.html"
      dom_dump_editor: "despacho_editor.html"
      screenshot_form: "despacho_form.png"
      screenshot_editor: "despacho_editor.png"

# Caminhos de erro / fallback observados durante a captura.
# Útil para o código defensivo no SEIWriter.
known_errors:
  - condition: "Tipo de processo não encontrado"
    selector: "div.infraMessageError"
    text_pattern: "tipo.*não.*permitido"
    handling: "raise descriptive error before clicking Salvar"
```

**Regra:** todos os seletores capturados devem ser **únicos e estáveis**. Para cada campo:
1. Tentar primeiro `id` (mais estável)
2. Fallback para `name` ou `data-*` attribute
3. Último recurso: CSS path baseado em estrutura
4. **Nunca** usar índices posicionais (`:nth-child(3)`) sem comentário explicativo
5. Se um campo só aparece após interação (ex.: hipótese legal após restrito), marcar `visible_after` com a dependência

---

## 6. Procedimento da sessão de captura

### 6.1 Setup (humano, ~5 min)

```powershell
# 1. cd no projeto
cd C:\Users\trabalho\Documents\automation\nanobotWork\nanobot

# 2. Atualizar
git pull origin dev

# 3. Ativar venv
.\.venv\Scripts\Activate.ps1

# 4. Garantir que claude está autenticado com Max
claude /login   # se ainda não autenticou

# 5. Garantir Playwright instalado
python -m playwright install chromium

# 6. Criar diretório de saída
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
mkdir -p "ufpr_automation/procedures_data/sei_capture/$ts"

# 7. (opcional) Salvar PDF dummy para testar file picker
# Pode ser qualquer PDF de uma página — coloque em
# ufpr_automation/procedures_data/sei_capture/dummy_tce.pdf

# 8. Lançar Claude Code
claude
```

### 6.2 Prompt de bootstrap (cole no Claude Code)

> **Importante:** este prompt assume que você está com o Claude Code aberto no diretório raiz `nanobot/` e que `ufpr_automation/SDD_SEI_SELECTOR_CAPTURE.md` (este arquivo) está commitado. Adapte o `<TIMESTAMP>` para o `$ts` que você criou no setup.

```
Leia ufpr_automation/SDD_SEI_SELECTOR_CAPTURE.md inteiro antes de qualquer
ação. Você vai executar a sprint descrita lá: capturar seletores DOM dos
3 formulários do SEI listados na §4 (iniciar_processo, incluir_documento_externo,
incluir_documento_despacho).

Restrições críticas:
- VOCÊ NÃO PODE SALVAR NADA NO SEI. Cancelar/fechar todo formulário sem salvar.
- VOCÊ NÃO PODE clicar em Assinar, Enviar Processo, Protocolar, ou Tramitar.
- O alvo é mapear DOM e fluxo de navegação, NÃO criar processos reais.

Saída:
- procedures_data/sei_capture/<TIMESTAMP>/sei_selectors.yaml (schema na §5)
- procedures_data/sei_capture/<TIMESTAMP>/*.html (DOM dumps)
- procedures_data/sei_capture/<TIMESTAMP>/*.png (screenshots)
- procedures_data/sei_capture/<TIMESTAMP>/CAPTURE_LOG.md (resumo + observações)

Plano de execução:
1. Escreva um script Python em scripts/capture_sei_selectors.py que:
   - Reaproveita ufpr_automation/sei/browser.py (launch_browser, auto_login)
   - Roda em modo headed
   - Para CADA form alvo:
     a. Navega até o form
     b. Captura screenshot (full page) e salva
     c. Captura page.content() e salva como .html
     d. Imprime/captura os <input>, <select>, <button>, <a> da área relevante
        com id, name, type, label associado
     e. CANCELA/FECHA o form sem salvar
   - Salva tudo em procedures_data/sei_capture/<TIMESTAMP>/raw/
2. Rode o script. Se der erro, debugue iterativamente.
3. Após a captura raw, leia os 3 .html e proponha o sei_selectors.yaml
   completo seguindo o schema da §5 do SDD.
4. Para o form incluir_documento_despacho, atenção especial ao iframe do
   editor rich-text — siga as instruções da §4.3.
5. Verifique se algum selector que VOCÊ propõe colide com a lista de tokens
   proibidos em ufpr_automation/sei/writer.py:_FORBIDDEN_SELECTORS. Se sim,
   marque guard_check: NEEDS_TOKEN_ADJUSTMENT no YAML e proponha como
   refinar a lista (mais específica, sem perder cobertura).
6. Escreva CAPTURE_LOG.md com:
   - Seções por form, riscos encontrados, decisões de fallback
   - Lista de campos que NÃO foram encontrados (e por quê)
   - Recomendações para o próximo step (wire-up no SEIWriter)

Se o login no SEI exigir interação humana (CAPTCHA, MFA), PARE e me peça
ajuda. Não tente bypass automatizado.

Comece lendo o SDD e em seguida o SEI_DOC_CATALOG.yaml + sei/writer.py +
sei/browser.py para entender o contexto.
```

### 6.3 Pontos de check humano durante a sessão

| Quando | O que verificar |
|---|---|
| Após o login no SEI | A janela headed mostra o dashboard? Sem CAPTCHA? |
| Antes do primeiro click em Salvar/Confirmar | **Interromper o agente.** Confirmar visualmente que ele cancelaria, não salvaria. |
| Após captura do form despacho | Ver se o editor abriu como popup ou iframe — confirmar com Claude Code |
| Final | Revisar o `sei_selectors.yaml` propsoto: cada `selector` tem `id` ou um caminho explicável? Algum nth-child suspeito? |

---

## 7. Integração no `sei/writer.py` (sessão seguinte)

Após o YAML estar revisado e commitado, **eu** (Claude na sessão seguinte) faço a integração. Plano:

1. **Criar `sei/writer_selectors.py`** — módulo novo que importa o `sei_selectors.yaml` e expõe constantes tipadas:
   ```python
   from typing import TypedDict
   class FormSelectors(TypedDict):
       nav_path: list[dict]
       fields: dict[str, dict]
       submit: dict
       success_indicator: dict
   
   def load_selectors() -> dict[str, FormSelectors]:
       """Lazy-load do YAML, cached."""
   ```

2. **Refatorar `SEIWriter._safe_click`** para também verificar contra a `_FORBIDDEN_SELECTORS` no caminho `nav_path` E no `submit.selector` de cada form. Se algum bater, falhar antes de rodar.

3. **Substituir os 3 `NotImplementedError`** em `sei/writer.py`:
   - `create_process` (line ~360)
   - `attach_document` (line ~225, dentro do `if not self._dry_run`)
   - `save_despacho_draft` (line ~430)
   
   Cada um vira: ler `load_selectors()[form_name]`, executar `nav_path`, preencher `fields`, screenshot pré-submit, `_safe_click(submit)`, esperar `success_indicator`, screenshot pós-submit, audit JSONL.

4. **Para `create_process`:** após o submit, extrair o `processo_id` real usando `success_indicator.processo_id_extractor.regex` e retornar no `CreateProcessResult.processo_id`.

5. **Para `save_despacho_draft`:** lidar com iframe — `page.frame_locator(editor.iframe_selector).locator(editor.body_selector).fill(filled_text)`, depois `_safe_click(editor.save_button.selector)`.

6. **Manter `dry_run` mode intacto** — o caminho dry_run continua não tocando em nada. A diferença é só no `if not self._dry_run` branch.

7. **Adicionar testes em `tests/test_sei_writer.py`**:
   - `test_load_selectors_yaml_exists_and_parses`
   - `test_no_form_selector_collides_with_forbidden_tokens`
   - `test_create_process_dryrun_returns_synthetic_id` (já deve existir? confirmar)
   - `test_attach_document_dryrun_logs_classification`
   - `test_save_despacho_draft_dryrun_uses_body_override`

---

## 8. Test plan pós-integração

**Fase 8.1 — Validação dry_run (sem rede SEI)**
```bash
SEI_WRITE_MODE=dry_run python -m pytest ufpr_automation/tests/test_sei_writer.py -v
```
Deve passar 100%.

**Fase 8.2 — Smoke dry_run end-to-end (sem rede SEI)**

Script novo em `scripts/smoke_estagios_dryrun.py`:
1. Mock de `SIGAClient` retornando `matricula_status="ATIVA"`, `reprovacoes_ultimo_semestre=0`, etc.
2. Mock de `SEIClient` retornando processos vazios (não duplicado)
3. Cria um `EmailData` fictício com TCE PDF
4. Chama o (futuro) `agir_estagios` node
5. Espera: `CreateProcessResult.success=True, dry_run=True, processo_id="DRYRUN-..."`
6. Espera: `AttachResult.success=True, dry_run=True, classification.sei_subtipo="Termo"`
7. Espera: `DraftResult.success=True, dry_run=True`
8. Espera: rascunho de email Gmail salvo (via mock)
9. Espera: `procedures_data/sei_writes/audit.jsonl` recebeu 3 registros com `mode=dry_run`

**Fase 8.3 — Smoke `live` em SEI de teste (com rede)**

```bash
SEI_WRITE_MODE=live python scripts/smoke_estagios_live.py --processo-teste 23075.000XXX/2026-XX
```

Critérios:
- O script cria um processo de teste, anexa o dummy_tce.pdf, escreve um despacho dummy
- **NÃO assina, NÃO envia, NÃO protocola** — o processo fica em rascunho
- Após o smoke: humano abre o SEI manualmente e CANCELA o processo de teste
- `audit.jsonl` recebe 3 registros com `mode=live` + screenshots reais

**Fase 8.4 — Rollback plan**

Se a Fase 8.3 falhar:
1. `SEI_WRITE_MODE=dry_run` no `.env` (restaura safe default)
2. Capturar logs + screenshots
3. Não tem nada irreversível pra reverter (não assinou nem enviou)

---

## 9. Critérios de sucesso desta sprint

A sprint está completa quando:

- [ ] `procedures_data/sei_capture/<timestamp>/sei_selectors.yaml` existe e segue o schema da §5
- [ ] Os 3 forms estão mapeados (iniciar_processo, incluir_documento_externo, incluir_documento_despacho)
- [ ] Cada `selector` proposto tem `id` estável OU uma justificativa em comentário
- [ ] DOM dumps `.html` salvos para cada form
- [ ] Screenshots `.png` salvos para cada form
- [ ] `CAPTURE_LOG.md` documenta riscos, fallbacks, e recomendações
- [ ] Nenhum documento foi salvo no SEI (auditável: o SEI de teste não tem processo novo nem doc novo)
- [ ] Nenhum selector capturado colide com `_FORBIDDEN_SELECTORS` SEM um plano de mitigação documentado
- [ ] Commit pronto para a sessão seguinte de wire-up

---

## 10. Riscos conhecidos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Login do SEI tem CAPTCHA / MFA novo | média | Sessão headed; humano resolve manualmente; salvar `state.json` para reuso (já implementado em `sei/browser.py`) |
| `Tipo de Processo` não está disponível na unidade do user | baixa | Capturar a mensagem de erro em `known_errors` para tratamento defensivo |
| `interessado` exige busca via picker (não free text) | alta | Capturar fluxo do picker no `nav_path`, anotar como `type: autocomplete` ou `type: modal_picker` |
| Editor de Despacho está em popup, não iframe | média | Capturar `page.context.pages` antes/depois do clique em Confirmar; se nova page apareceu, é popup. Atualizar `editor.type: popup` no YAML. |
| TinyMCE não aceita `fill()` direto | alta | Usar `page.frame_locator(...).locator("body").click()` antes do `fill()`, ou `evaluate("document.body.innerHTML = ...")` |
| Selector do "Salvar" do editor bate com `_FORBIDDEN_SELECTORS` (ex.: classe contém "submit") | média | Marcar `guard_check: NEEDS_TOKEN_ADJUSTMENT` e propor refinamento da lista (substring mais específica) |
| Algum campo só aparece após scroll | baixa | Capturar `await page.locator(selector).scroll_into_view_if_needed()` no `nav_path` |
| Timeout no `auto_login` (rede lenta) | baixa | Aumentar timeout em `sei/browser.py:auto_login` para 60s nessa sprint |
| Sessão expira durante captura | média | Salvar `state.json` no início; se expirar, re-rodar `auto_login` |
| Captura usa MUITA quota Max | baixa | A sessão é one-shot, ~30-60min de Claude Code = ~$3-10 equivalente em tokens, bem dentro da quota mensal |

---

## 11. Out of scope (deixar para sprints futuras)

- ❌ **Wire-up real no `sei/writer.py`** — vai para a sessão SEGUINTE depois desta captura
- ❌ **`agir_estagios` node** — depende do wire-up
- ❌ **Captura de seletores SIGA** — escopo separado, não bloqueia Marco IV (SIGA já tem read-only working)
- ❌ **Captura de "Iniciar Processo" para outros tipos** (Estágio Obrigatório, Aproveitamento, etc.) — fazer um por vez, começar com Não Obrigatório
- ❌ **Computer use** (controle visual) — não disponível no plano Max, e Playwright via Bash atende
- ❌ **Cópia/atualização do `state.json` da sessão de teste para produção** — sessões separadas; não misturar credenciais

---

## 12. Próximos passos depois desta sprint

1. **Revisar com o humano** o `sei_selectors.yaml` e o `CAPTURE_LOG.md`
2. **Commit** os artefatos em `procedures_data/sei_capture/<timestamp>/`
3. **Sessão de wire-up** (Claude Code com este SDD + os artefatos como input):
   - Criar `sei/writer_selectors.py`
   - Substituir os 3 `NotImplementedError`
   - Adicionar testes
   - Smoke dry_run
4. **Sessão de validação live** (humano + Claude Code):
   - Smoke live em SEI de teste
   - Cancelar o processo de teste manualmente após
5. **Atualizar TASKS.md** removendo o item bloqueante e marcando Marco IV como ✅
6. **Habilitar `SEI_WRITE_MODE=live`** no `.env` de produção (com backup do `.env` atual)
7. **Rodar `--limit 1` em produção** com um TCE real e auditar manualmente

---

## Apêndice A — Mapeamento `sei_selectors.yaml` ↔ `SEIDocClassification`

Para `attach_document`, a tradução do `SEIDocClassification` (de `sei/writer_models.py`) para os campos do form `incluir_documento_externo` é:

| `SEIDocClassification` | Field do form |
|---|---|
| `sei_tipo` (sempre "Externo" aqui) | escolha inicial "Externo" no `nav_path` |
| `sei_subtipo` ("Termo" / "Relatório") | `tipo_documento` |
| `sei_classificacao` ("Inicial"/"Aditivo"/...) | `nome_na_arvore` (ou sub-select se existir) |
| `sigiloso` (default True) | `nivel_acesso_restrito` (radio) |
| `motivo_sigilo` (default "Informação Pessoal") | `hipotese_legal` |
| `data_documento` (vazio = hoje) | `data_documento` |

Para `create_process`, a tradução é direta:

| Argumento | Field |
|---|---|
| `tipo_processo` | `tipo_processo` |
| `especificacao` | `especificacao` |
| `interessado` | `interessado` |
| `motivo` (opcional) | `observacoes` |

Para `save_despacho_draft`, o `body_override` (ou template do TemplateRegistry) é o conteúdo a colar no `editor.body_selector`. Os outros campos do form inicial (`descricao`, `nome_na_arvore`) podem ficar vazios ou usar `tipo` como label curto.

---

## Apêndice B — Comando único para iniciar a próxima sessão

```powershell
cd C:\Users\trabalho\Documents\automation\nanobotWork\nanobot
git pull origin dev
.\.venv\Scripts\Activate.ps1
$ts = Get-Date -Format "yyyyMMdd_HHmmss"
mkdir -p "ufpr_automation/procedures_data/sei_capture/$ts"
Write-Host "Diretório de captura: ufpr_automation/procedures_data/sei_capture/$ts"
Write-Host "Pronto. Rode 'claude' e cole o prompt da §6.2 do SDD."
claude
```
