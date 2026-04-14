# SIGA Selectors Manifest — Schema

`siga_selectors.yaml` is the grounded manifest of Playwright selectors used
by `ufpr_automation/siga/client.py`. It is produced by the grounder
(`python -m ufpr_automation.agent_sdk.siga_grounder`) from the UFPR Aberta
BLOCO 3 tutorial markdown.

## Canonical location

```
ufpr_automation/procedures_data/siga_capture/<timestamp>/siga_selectors.yaml
```

The loader (`ufpr_automation.siga.selectors`) resolves the active manifest
via this precedence:

1. `$SIGA_SELECTORS_PATH` env var (absolute path)
2. `procedures_data/siga_capture/latest/siga_selectors.yaml`
3. Most recently modified `siga_selectors.yaml` under any timestamped subdir
   of `procedures_data/siga_capture/`

Tests point at `ufpr_automation/tests/fixtures/siga_selectors.example.yaml`
via `SIGA_SELECTORS_PATH`.

## Schema v1

```yaml
meta:
  schema_version: 1            # REQUIRED, currently 1
  captured_at: "2026-04-14T00:00:00Z"
  source_tutorial: "base_conhecimento/ufpr_aberta/BLOCO_3.md"
  source_raw_html: "G:/Meu Drive/ufpr_rag/docs/ainda_n_ingeridos/ufpr_aberta/bloco_3_secao_3/"
  siga_url: "https://siga.ufpr.br/..."
  notes: "free-form human notes about this capture"

login:                         # REQUIRED
  url: "/login"                # path or absolute URL
  fields:
    username:
      selector: "#login"
      kind: "input"            # input | password | select
    password:
      selector: "#senha"
      kind: "password"
  submit:
    selector: "#btnEntrar"
  logged_in_indicator:
    selector: "a:has-text('Sair')"

navigation:                    # OPTIONAL — named paths through the menu
  home:
    url: "/sistemasweb/home"
  student_search:
    menu_path:
      - "text=Consulta"
      - "text=Alunos"
    url_hint: "/consulta/aluno"

screens:                       # REQUIRED — per-screen selector blocks
  student_search:
    description: "Form to look up student by GRR"
    fields:
      grr_input:
        selector: "input[name='matricula']"
        kind: "input"
    submit_selector: "button:has-text('Consultar')"
    result_indicator: "#dadosAluno"

  student_detail:
    description: "Page showing student's academic info"
    fields:
      nome:
        selector: "#dados_aluno_nome"
        extract: "text"        # text | text_list | integer | date
      curso:
        selector: "#dados_aluno_curso"
        extract: "text"
      situacao:
        selector: "#dados_aluno_situacao"
        extract: "text"

# OPTIONAL documentation block — lists the selectors the SIGA client
# must NEVER click (SIGA is read-only by policy). The validator
# ALLOWS these strings to appear ONLY inside this section; anywhere
# else they raise SIGASelectorsError on load.
forbidden_selectors:
  - "text=Matricular"
  - "text=Alterar"
  - "#btnSalvar"
```

## Field kinds

| `kind`      | Expected element                        | How the client interacts                         |
|-------------|-----------------------------------------|--------------------------------------------------|
| `input`     | `<input type=text>`                      | `.fill(value)`                                   |
| `password`  | `<input type=password>`                  | `.fill(value)` (logged at DEBUG, never INFO)     |
| `select`    | `<select>`                                | `.select_option(label=...)` or `.select_option(value=...)` |
| *(missing)* | treated as text/container by default     | `.text_content()` via `extract`                  |

## Extract strategies

| `extract`   | Return type   | Notes                                                       |
|-------------|---------------|-------------------------------------------------------------|
| `text`      | `str`          | `.text_content().strip()`; empty → `None`                    |
| `text_list` | `list[str]`    | `.all_text_contents()`; empty list allowed                   |
| `integer`   | `int \| None`  | Parses first group of digits; `None` if nothing found        |
| `date`      | `date \| None` | Parses `dd/mm/yyyy`; `None` on mismatch                       |

## Validation

The loader refuses manifests that:

- Lack any of the required top-level keys (`meta`, `login`, `screens`)
- Declare a `schema_version` other than 1
- Contain a leaf selector string matching `_FORBIDDEN_SELECTORS`, **except**
  inside the dedicated `forbidden_selectors` documentation section
- Fail to parse as YAML

## Evolving the schema

When adding new screens or fields, prefer authoring them inside the
grounder (`agent_sdk/siga_grounder.py`) so the Claude CLI invocation
produces them automatically on re-run. Only touch this document when
adding a new top-level section, a new `kind`, or a new `extract`
strategy.
