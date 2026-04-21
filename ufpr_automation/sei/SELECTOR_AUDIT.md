# SELECTOR_AUDIT — sei_selectors.yaml vs POPs canônicos

Manifesto auditado: `G:/Meu Drive/ufpr_automation_files/sei_selectors.yaml` (capturado 2026-04-13, SEI 5.0.3, CCDG).

## Resumo

| POP | Form no manifesto | Status |
|-----|-------------------|--------|
| POP-5 Iniciar Processo | `iniciar_processo` | ✅ Cobre fluxo Estágios; gap menor em `grau_sigilo` |
| POP-25 Incluir Doc Externo | `incluir_documento_externo` | ✅ Completo |
| POP-19 Criar Doc Interno (Despacho) | `incluir_documento_despacho` | ✅ Suficiente (só cobre Texto Inicial=Nenhum) |
| POP-20 Editar Doc Interno | `incluir_documento_despacho.editor` | ✅ Para draft inicial; gap pra re-edit |
| POP-38 Acompanhamento Especial | `acompanhamento_listar` / `acompanhamento_gerenciar` / `acompanhamento_cadastrar` | ✅ **Capturado 2026-04-21** (ainda não wired no manifesto — ver §1) |

## Gaps detalhados

### 1. POP-38 Acompanhamento Especial — selectors capturados 2026-04-21

Capturas rodadas via `scripts/sei_drive.py --target acompanhamento_especial_menu` + `--target acompanhamento_especial_processo` (outputs: `procedures_data/sei_capture/20260421_005928/` + `20260421_010216/`). Cross-check na raw HTML confirma o layout completo (v1 da análise ignorou o `<img onclick>`, corrigido).

**Nav paths — 3 telas, 2 entradas:**

```yaml
acompanhamento_especial:
  # ──────────────────────────────────────────────────────────────
  # Entrada A: Menu lateral → visão unidade-wide
  # ──────────────────────────────────────────────────────────────
  menu_unidade:
    action: "acompanhamento_listar"
    selector_menu: 'a:has-text("Acompanhamento Especial")'   # main frame
    frame: null
    # Tela lista TODOS os processos da unidade organizados por grupo.
    # Affordances relevantes:
    buttons:
      listar_grupos:
        # Admin dos grupos — criar/editar/excluir grupos da unidade.
        selector: "#btnGrupoAcompanhamentoListar"
        target_action: "grupo_acompanhamento_listar"
        accesskey: "L"

  # ──────────────────────────────────────────────────────────────
  # Entrada B: Processo aberto → ícone na toolbar
  # ──────────────────────────────────────────────────────────────
  toolbar_icon:
    selector: 'xpath=//a[.//img[@title="Acompanhamento Especial"]]'
    frame: "ifrConteudoVisualizacao"
    # Comportamento condicional:
    #   - Se processo JÁ tem acompanhamento → vai pra gerenciar_processo (list page)
    #   - Se processo NUNCA teve acompanhamento → vai direto pra cadastrar (form)

  # ──────────────────────────────────────────────────────────────
  # Tela: lista dos acompanhamentos deste processo
  # ──────────────────────────────────────────────────────────────
  gerenciar_processo:
    action: "acompanhamento_gerenciar"
    landing_frame: "ifrVisualizacao"
    page_title: "Acompanhamentos Especiais do Processo <NUMERO>"
    buttons:
      adicionar:
        selector: "#btnAdicionar"
        # onclick = location.href='...acao=acompanhamento_cadastrar...'
        target_action: "acompanhamento_cadastrar"
      excluir:
        selector: "#btnExcluir"
        onclick: "acaoExclusaoMultipla()"
    # Cada linha da lista tem link de editar (navega pro mesmo form cadastrar
    # com #hdnIdAcompanhamento pré-preenchido).

  # ──────────────────────────────────────────────────────────────
  # Tela: form create/edit de Acompanhamento
  # ──────────────────────────────────────────────────────────────
  cadastrar:
    action: "acompanhamento_cadastrar"
    frame: "ifrVisualizacao"
    # Mesmo form atende create + edit. Diferenciado apenas por:
    #   #hdnIdAcompanhamento vazio = create, preenchido = edit
    # Título da tela: "Novo Acompanhamento Especial" (create) vs.
    #                 "Alterar Acompanhamento Especial" (edit)
    fields:
      grupo:
        type: "select"
        selector: "#selGrupoAcompanhamento"
        match_by: "text"   # preferir option text exato
        default_for_estagio_nao_obrig: "Estágio não obrigatório"
      novo_grupo:
        # Ícone "+" ao lado do select. Abre MODAL via infraAbrirJanelaModal.
        # Usado quando o grupo desejado ainda não existe.
        type: "image_modal_trigger"
        selector: "#imgNovoGrupoAcompanhamento"
        onclick: "cadastrarGrupoAcompanhamento()"
        modal_action: "grupo_acompanhamento_cadastrar"
        modal_size: "700x300"
      observacao:
        type: "textarea"
        selector: "#txaObservacao"
        rows: 4
    hidden:
      id_acompanhamento: "#hdnIdAcompanhamento"   # vazio=create, preenchido=edit
      id_protocolo: "#hdnIdProtocolo"
    submit:
      # Atenção: NÃO é #btnSalvar (é <button type="submit" name="sbm...">).
      selector: 'button[name="sbmCadastrarAcompanhamento"]'
      value: "Salvar"
      accesskey: "S"
    cancel:
      selector: "#btnCancelar"
      accesskey: "C"

  # ──────────────────────────────────────────────────────────────
  # Modal: criar novo grupo (inline no form cadastrar)
  # ──────────────────────────────────────────────────────────────
  novo_grupo_modal:
    # Capturado 2026-04-21 (target acompanhamento_novo_grupo_modal).
    # infraAbrirJanelaModal injeta um iframe com a URL abaixo dentro da
    # mesma página DOM (vira um frame extra — 6 frames após click vs 4 antes).
    action: "grupo_acompanhamento_cadastrar"
    status: "captured"
    page_title: "SEI - Novo Grupo de Acompanhamento"
    form_id: "#frmGrupoAcompanhamentoCadastro"
    fields:
      nome:
        type: "text"
        selector: "#txtNome"
        maxlength: 150
    hidden:
      # vazio = create; preenchido = edit (mesmo form atende ambos).
      id_grupo: "#hdnIdGrupoAcompanhamento"
    submit:
      selector: 'button[name="sbmCadastrarGrupoAcompanhamento"]'
      value: "Salvar"
    cancel:
      # Modal NÃO tem botão Cancelar. Fechar via:
      strategies:
        - "page.keyboard.press('Escape')"
        - "click fora do modal (overlay)"
```

**Correções vs. inferência anterior (pre-captura, v0):**
1. ❌ v0 dizia `#txtNomeGrupo` era no form cadastrar → ✅ está no MODAL separado (acao `grupo_acompanhamento_cadastrar`), aberto via ícone `#imgNovoGrupoAcompanhamento`.
2. ❌ `#txaDescricao` → ✅ `#txaObservacao`.
3. ❌ `#btnSalvar` → ✅ `button[name="sbmCadastrarAcompanhamento"]` (atributo `name`, não `id`).
4. ❌ "1 processo = 1 grupo" → ✅ processo pode ficar em N grupos; gerenciar_processo tem multi-seleção (Excluir via checkbox).
5. ⚠️ v1 (primeira passada desta sessão) dizia "não existe Novo Grupo no form" — **errado**. O `<img>` com onclick me escapou porque a query JS não pegava `img[onclick]`. Query do driver atualizada; re-runs futuros capturam.

**Próximos passos para wire-up:**
- [x] Capturar modal `grupo_acompanhamento_cadastrar` (rodado 2026-04-21)
- [ ] Adicionar entrada `acompanhamento_especial` no `sei_selectors.yaml` do Drive
- [ ] Implementar live path em `sei/writer.py:add_to_acompanhamento_especial`:
  1. Navegar toolbar → se cair em `gerenciar_processo`, clicar `#btnAdicionar`; se cair em `cadastrar` direto, prosseguir
  2. Selecionar grupo por texto via `#selGrupoAcompanhamento`
  3. Se grupo não existir: clicar `#imgNovoGrupoAcompanhamento` → esperar o iframe com URL `grupo_acompanhamento_cadastrar` aparecer → preencher `#txtNome` → submit `button[name="sbmCadastrarGrupoAcompanhamento"]` → aguardar modal fechar e o novo grupo aparecer selecionado no `#selGrupoAcompanhamento` do form pai
  4. Preencher `#txaObservacao` (opcional)
  5. Submit `button[name="sbmCadastrarAcompanhamento"]` (modo live) ou Cancelar (dry-run)
- [ ] Testar em dry-run + live contra processo de smoke

### 2. POP-5 — `grau_sigilo` ausente

Manifesto tem `nivel_acesso` + `hipotese_legal` condicionais. Não tem `grau_sigilo` (dropdown que aparece quando `nivel_acesso=sigiloso`). Para Estágios default é `publico` — **não é blocker**. Documentar pra futuro chat-driven agent que possa escolher Sigiloso.

### 3. POP-19 — Texto Inicial alternativos não mapeados

Manifesto só cobre `texto_inicial_nenhum`. POP-19 também oferece:
- `Documento Modelo` (input de Protocolo do modelo)
- `Texto Padrão` (dropdown de textos pré-cadastrados)

Tier 0 sempre usa Nenhum (estratégia atual: despacho body 100% gerado pelo writer), então **não é blocker**. Relevante se adotarmos POP-23 (Texto Padrão) no futuro pra simplificar despachos repetitivos.

### 4. POP-20 — Re-edit path não mapeado

Manifesto cobre o **editor inicial** (abre após Salvar do form de criação). Para re-editar um despacho já salvo (POP-20 fluxo típico), falta o nav:
- Click no número do documento na árvore
- Click em ícone "Editar Conteúdo"
- Mesmo popup CKEditor reabre

Tier 0 não re-edita (strategy: gerar certo na primeira). **Não é blocker**. Relevante pro chat-driven futuro ("corrige esse parágrafo no despacho X").

## Coberturas validadas

- ✅ `nivel_acesso` com overlaid labels (`#lbl*` não `#opt*`) — evita pitfall comum de click não registrar
- ✅ `ifrVisualizacao` frame path para Externo/Despacho
- ✅ CKEditor 5 contenteditable com `click_then_keyboard_type` (não `.fill()`)
- ✅ `button.salvar__buttonview` estável e sem token forbidden
- ✅ Forbidden button `data-cke-tooltip-text^="Assinar"` documentado como bloqueado
- ✅ `hdnAssuntos` pre-fill não precisa ser re-preenchido (gotcha evitado)
- ✅ Dialogs `missing_required_*` com handler registrado antes do submit

## Sprint 3 fix — relação com o manifesto

Fix aplicado em `writer.py:save_despacho_draft` (2026-04-14):
- Usa `#optNenhum` (selector `fields.texto_inicial_nenhum.selector`) com `.check()` + `.is_checked()` — antes usava só `label` click.
- Belt-and-suspenders: `Ctrl+A + Delete` no CKEditor body antes de digitar, pra limpar template default caso Nenhum não registre.

Nenhum selector novo foi adicionado — o manifesto já tinha `#optNenhum` como `selector` e `#lblNenhum` como `label`.

## Próxima captura — checklist

Ao rodar próxima captura via `scripts/sei_drive.py`:

1. Incluir form `acompanhamento_especial` (ver seção 1 acima) — desbloqueia task #7.
2. Opcional: `grau_sigilo` dropdown (seção 2).
3. Opcional: re-edit path de Despacho (seção 4).
