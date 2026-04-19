# Guia de Navegacao SEI

Referencia para navegacao Playwright no SEI (Sistema Eletronico de Informacoes). Seletores capturados via `scripts/sei_drive.py` (Sprint 1, 2026-04-13). A automacao tem **write limitado** — cria processos, anexa documentos, salva despachos rascunho. **NUNCA** assina, protocola, envia ou conclui processos.

---

## 1. Login — Direto

```
URL:      https://sei.ufpr.br
Form:     input[id="txtUsuario"]  +  input[id="pwdSenha"]
Submit:   button[id="sbmLogin"]
Indicador: presenca de iframe principal (#ifrVisualizacao)
Unidade:  UFPR/R/AC/CCDG (Coordenacao do Curso de Design Grafico)
```

Credenciais em `.env`: `SEI_USERNAME`, `SEI_PASSWORD`. `sei/browser.py` lida com login e sessao.

---

## 2. Estrutura da pagina

O SEI usa um **frameset** com dois iframes principais:
- **Arvore de processos** (iframe esquerdo): lista de processos na unidade
- **Conteudo** (`#ifrVisualizacao`): visualizacao de documentos e formularios

A maioria das acoes acontece dentro de `#ifrVisualizacao`. O `SEIWriter` navega dentro do iframe correto automaticamente.

---

## 3. Acoes principais (menu do processo)

| Acao | Seletor | Notas |
|---|---|---|
| Iniciar Processo | `a[href*="processo_iniciar"]` | Abre formulario de tipo de processo |
| Incluir Documento | `img[title="Incluir Documento"]` | Tipo interno (Despacho) ou externo (PDF) |
| Consultar/Alterar | `img[title="Consultar/Alterar Processo"]` | Metadados |
| Acompanhamento Especial | `img[title="Acompanhamento Especial"]` | Classificar para visualizacao |
| **Enviar Processo** | `img[title="Enviar Processo"]` | **PROIBIDO pela automacao** |
| **Assinar Documento** | `img[title="Assinar"]` | **PROIBIDO pela automacao** |
| **Concluir Processo** | `img[title="Concluir Processo"]` | **PROIBIDO pela automacao** |

---

## 4. Formulario "Iniciar Processo"

```
Tipo do Processo:  select#selTipoProcedimento (ou busca por texto)
Especificacao:     input#txtDescricao  → "NOME ALUNO - GRR20XXXXXX"
Nivel de Acesso:   radio[name="rdoNivelAcesso"]
                   "Publico" (default) | "Restrito" | "Sigiloso"
Hipotese Legal:    select#selHipoteseLegal (se Restrito)
```

---

## 5. Formulario "Incluir Documento Externo"

```
Tipo do Documento: select#selSerie ou busca texto  → "Termo" (preferido)
                   Fallback: "Documento" + Nome na Arvore descritivo
Data do Documento: input#txtDataElaboracao
Formato:           radio → "Nato-digital" ou "Digitalizado"
Tipo Conferencia:  select → "Documento Original" (se nato-digital)
                          | "Copia Autenticada Administrativamente" (se OCR/scan)
Nivel de Acesso:   radio → "Restrito"
Hipotese Legal:    select → "Informacao Pessoal (Art. 31...)"
Arquivo:           input[type="file"]
```

**Regra `tipo_conferencia`**: `Nato Digital` quando a origem e digital; `Copia Autenticada Administrativamente` quando foi escaneado (dependeu de OCR).

---

## 6. Formulario "Despacho" (documento interno)

```
Tipo Documento:    "Despacho" (selecionar na lista)
Texto Padrao:      select → templates do TemplateRegistry (Neo4j)
Corpo:             iframe CKEditor
Nivel de Acesso:   "Publico" (default para Despachos)
```

O `SEIWriter.save_despacho_draft` usa `Ctrl+A → Delete → colar body` no CKEditor.

---

## 7. Operacoes da automacao (SEIWriter)

| Metodo | O que faz | Mode |
|---|---|---|
| `create_process` | Iniciar Processo → preenche tipo, especificacao, nivel | dry_run / live |
| `attach_document` | Incluir Documento Externo → upload PDF | dry_run / live |
| `save_despacho_draft` | Incluir Despacho → preenche corpo via template | dry_run / live |
| `add_to_acompanhamento_especial` | Classificar processo para acompanhamento | dry_run only (POP-38) |

**Operacoes PROIBIDAS** (nao existem metodos, `_FORBIDDEN_SELECTORS` bloqueia):
- `sign()` — assinar documento
- `send()` — enviar/tramitar processo
- `protocol()` — protocolar
- `finalize()` — concluir processo

6 testes regressivos em `test_sei_writer.py::TestWriterArchitecturalSafety` garantem ausencia + scan estatico do source.

---

## 8. Tipos de processo mais comuns

| Tipo SEI | Qtd | Categoria automacao |
|---|---|---|
| Graduacao/Ensino Tecnico: Estagios nao Obrigatorios | 238 | Estagios |
| Administracao Geral: Informacoes e Documentos | 132 | Outros |
| Graduacao: Registro de Diplomas | 62 | Diplomacao |
| Graduacao/Ensino Tecnico: Estagio Obrigatorio | 60 | Estagios |
| Graduacao/Ensino Tecnico: Dispensa/Isencao/Aproveitamento | 60 | Academico |
| Graduacao: Programa de Voluntariado Academico | 42 | Formativas |
| Graduacao: Matriculas | 30 | Academico |
| Graduacao: Solicitacao de Trancamento/Destrancamento | 13 | Academico |
| Graduacao: Cancelamento por Abandono | 12 | Academico |
| Graduacao: Colacao de Grau com/sem Solenidade | 11+5+3 | Diplomacao |

---

## 9. Fluxo de Estagios no SEI (apos verificacao no SIGA)

```
← vindo da verificacao SIGA (ver NAVEGACAO_SIGA.md)
  |
  v
SEI: Iniciar Processo
  Tipo: "Graduacao/Ensino Tecnico: Estagios nao Obrigatorios"
  Especificacao: "NOME ALUNO - GRR20XXXXXX"
  Nivel: Restrito (Informacao Pessoal)
  |
  v
SEI: Incluir Documento Externo
  Tipo: "Termo" (TCE)
  Formato: Nato-digital (ou Digitalizado se OCR)
  Upload: TCE.pdf
  |
  v
SEI: Incluir Despacho
  Corpo: template do TemplateRegistry (Neo4j)
  Assinatura: HUMANO (automacao nao assina)
  |
  v
Rascunhar email de acuse ao aluno (Gmail draft, human-in-the-loop)
```

---

## 10. Manifest de Seletores

| Arquivo | Producao | Validacao |
|---|---|---|
| `procedures_data/sei_capture/.../sei_selectors.yaml` | `scripts/sei_drive.py` | `sei/writer_selectors.py` (forbidden guard) |

Carrega lazily, valida contra `_FORBIDDEN_SELECTORS` no load, consumido por `sei/writer.py`.

---

## 11. Notas Tecnicas

- **Framesets**: o SEI usa iframes. Navegacao Playwright precisa `frame_locator("#ifrVisualizacao")` para acessar o conteudo.
- **CKEditor**: o editor de despachos e um CKEditor dentro de um iframe. O `save_despacho_draft` limpa com Ctrl+A+Delete antes de colar.
- **Sessao**: `_session_browser.py` persiste `storage_state` em `session_data/state.json`.
- **Pre-warm (opt-in)**: o no `prewarm_sessions` em `graph/nodes.py` roda uma vez antes do fan-out do Fleet e, se `storage_state` do SEI estiver mais velho que `PREWARM_SESSIONS_MAX_AGE_H` (default 6h), dispara `auto_login` sequencial. Desliga a race de N logins paralelos pelo mesmo `state.json`. Ativar com `PREWARM_SESSIONS_ENABLED=true` quando batch grande em prod expuser a race; skip automatico se nenhum email menciona SEI/GRR/23075.
- **Audit trail**: toda operacao do `SEIWriter` gera screenshot + DOM dump + JSONL em `SEI_WRITE_ARTIFACTS_DIR`.
- **`SEI_WRITE_MODE`**: `dry_run` (default, seguro — loga intencao sem clicar) ou `live` (Playwright completo). Sprint 3 validado em 2026-04-16 (processo fictício `23075.022027/2026-22`); produção continua em `dry_run` até Fleet smoke em batch real.
- **POPs**: 60 tutoriais oficiais em `base_conhecimento/SEI-tutotiais/`. Triagem A/B/C em `SEI-tutotiais/README.md`.
