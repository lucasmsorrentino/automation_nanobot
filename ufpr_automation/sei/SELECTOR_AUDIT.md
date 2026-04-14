# SELECTOR_AUDIT — sei_selectors.yaml vs POPs canônicos

Manifesto auditado: `G:/Meu Drive/ufpr_automation_files/sei_selectors.yaml` (capturado 2026-04-13, SEI 5.0.3, CCDG).

## Resumo

| POP | Form no manifesto | Status |
|-----|-------------------|--------|
| POP-5 Iniciar Processo | `iniciar_processo` | ✅ Cobre fluxo Estágios; gap menor em `grau_sigilo` |
| POP-25 Incluir Doc Externo | `incluir_documento_externo` | ✅ Completo |
| POP-19 Criar Doc Interno (Despacho) | `incluir_documento_despacho` | ✅ Suficiente (só cobre Texto Inicial=Nenhum) |
| POP-20 Editar Doc Interno | `incluir_documento_despacho.editor` | ✅ Para draft inicial; gap pra re-edit |
| POP-38 Acompanhamento Especial | — | ❌ **Completamente ausente** |

## Gaps detalhados

### 1. POP-38 Acompanhamento Especial — BLOCKER pro task #7

Nenhum form `acompanhamento_especial` no manifesto. Precisa captura nova via `scripts/sei_drive.py`. Selectors esperados (inferidos do POP):

```yaml
acompanhamento_especial:
  nav_path:
    - {action: "open_process"}
    - {action: "click", selector: '<ícone estrela/Acompanhamento Especial na toolbar>'}
  fields:
    grupo:
      type: "select_or_create"
      selector: "#selGrupoAcompanhamento"          # TODO: confirmar
      new_group_button: "<botão Novo Grupo>"       # TODO: confirmar
      new_group_name_input: "#txtNomeGrupo"        # TODO: confirmar
      default_for_estagio_nao_obrig: "Estágio não obrigatório"
    descricao:
      type: "textarea"
      selector: "#txaDescricao"                    # TODO: confirmar
  submit:
    selector: "#btnSalvar"
  constraint: "1 processo = 1 grupo (POP-38 Atenção)"
```

**Ação**: quando próxima captura rodar, incluir este form. Task #7 depende.

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
