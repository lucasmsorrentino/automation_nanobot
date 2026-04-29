# Plano: substituir `BlockingScheduler` foreground por Windows Scheduled Tasks

> **Status**: pendente — para ser executado no **PC de casa** (mais hardware), via `git pull` + Claude Code.
> **Criado em**: 2026-04-29 (PC de trabalho).
> **Branch**: `dev`.

## Contexto

O scheduler do `ufpr_automation` parou em **2026-04-27 às 08:02:38**. Faltam ~5 execuções desde então (27/04 13h e 17h, 28/04 inteiro, 29/04 8h). Inbox acumulando.

**Causa raiz** (já investigada): `start_scheduler()` em [scheduler.py:127](scheduler.py) chama `BlockingScheduler.start()`, que bloqueia o terminal. O processo só roda enquanto o terminal está aberto e o usuário logado. Provavelmente terminal foi fechado / usuário deslogou / PC reiniciou. Sem Windows Service, sem Scheduled Task, sem wrapper de auto-restart.

**Não é bug de código.** [scheduler.py](scheduler.py) e [cli/commands.py:291-299](cli/commands.py) estão corretos. A fragilidade é arquitetural — execução em foreground.

**Solução decidida**: substituir o `BlockingScheduler` em foreground por **3 Windows Scheduled Tasks** chamando `--schedule --once` às 08:00, 13:00 e 17:00. Roda mesmo com usuário deslogado.

## Pré-requisitos a confirmar no PC de casa

1. **Repo atualizado**: `git pull origin dev` na raiz do projeto.
2. **Venv funcional**: `.venv\Scripts\python.exe --version` retorna Python 3.12.x. Se não existir o venv ou faltar `apscheduler`:
   ```bash
   python -m venv .venv
   .venv\Scripts\pip install -e ".[marco2]"
   ```
3. **`.env` válido** em `ufpr_automation\.env` (Gmail, SEI, Telegram, LLM keys). Se vier de outro PC via Drive, conferir paths e credenciais.
4. **Timezone do SO**: `Get-TimeZone` deve retornar `E. South America Standard Time` (UTC-03:00, Brasília). Compatível com `SCHEDULE_TZ=America/Sao_Paulo`.
5. **Identificar a raiz absoluta do projeto no PC de casa** — provavelmente diferente de `C:\Users\trabalho\Documents\automation\nanobotWork\nanobot`. Anotar e usar nos passos abaixo (substituir `<RAIZ>`).
6. **Identificar o usuário Windows** (`whoami` no terminal) — substituir `<USUARIO_WINDOWS>` abaixo.

## Passo 1 — Criar wrapper batch

Criar `<RAIZ>\scripts\run_scheduled_once.bat`:

```bat
@echo off
REM Wrapper invocado pelo Windows Task Scheduler para rodar 1 ciclo do pipeline.
REM Logs do wrapper (incluindo erros de bootstrap antes do logger Python iniciar)
REM vão para logs\task_scheduler_wrapper.log; logs do pipeline continuam em
REM logs\scheduler.log (escritos por run_scheduled_pipeline).

cd /d "<RAIZ>"

set PYTHONIOENCODING=utf-8

REM Executa via venv local — NÃO usar python global do sistema.
".venv\Scripts\python.exe" -m ufpr_automation --schedule --once >> "logs\task_scheduler_wrapper.log" 2>&1

exit /b %ERRORLEVEL%
```

Por que `.bat` em vez de `.ps1`: Task Scheduler chama `.bat` direto sem precisar configurar `ExecutionPolicy`; mais portável.

Garantir que `<RAIZ>\logs\` existe (já existe se o scheduler antigo já rodou alguma vez).

## Passo 2 — Registrar 3 Windows Scheduled Tasks

Abrir terminal como o usuário (não precisa admin) e rodar 3 vezes, uma por horário:

```bat
schtasks /create ^
  /tn "UFPR_Pipeline_08h" ^
  /tr "\"<RAIZ>\scripts\run_scheduled_once.bat\"" ^
  /sc daily /st 08:00 ^
  /ru "<USUARIO_WINDOWS>" /rp * ^
  /rl LIMITED ^
  /f
```

```bat
schtasks /create ^
  /tn "UFPR_Pipeline_13h" ^
  /tr "\"<RAIZ>\scripts\run_scheduled_once.bat\"" ^
  /sc daily /st 13:00 ^
  /ru "<USUARIO_WINDOWS>" /rp * ^
  /rl LIMITED ^
  /f
```

```bat
schtasks /create ^
  /tn "UFPR_Pipeline_17h" ^
  /tr "\"<RAIZ>\scripts\run_scheduled_once.bat\"" ^
  /sc daily /st 17:00 ^
  /ru "<USUARIO_WINDOWS>" /rp * ^
  /rl LIMITED ^
  /f
```

Flags:
- `/ru "<USUARIO_WINDOWS>"` + `/rp *` — roda como o usuário; `/rp *` pede a senha interativamente (cifra na hora) e habilita "run whether user is logged on or not".
- `/rl LIMITED` — privilégios padrão (não eleva a admin); suficiente porque o pipeline só lê email e escreve em `logs/`, `procedures_data/` e `G:\Meu Drive\`.
- `/sc daily /st HH:00` — trigger diário no horário-alvo (timezone do SO).
- `/f` — sobrescreve se já existir.

## Passo 3 — Limpar o backlog imediatamente

Logo após criar as tasks, disparar uma manualmente para processar os ciclos perdidos:

```bat
schtasks /run /tn "UFPR_Pipeline_08h"
```

Esse comando dispara o `.bat` agora — mesmo path do disparo automático, então valida wrapper + venv + .env + scheduler.py end-to-end no fluxo real.

**Tempo esperado**: 3-15 min, dependendo do volume de email acumulado (~5 ciclos perdidos × emails/ciclo).

Acompanhar com:
```bash
tail -f logs/scheduler.log
```

## Passo 4 — Validar

```bat
schtasks /query /tn "UFPR_Pipeline_*" /fo TABLE
```
Deve listar 3 tasks com status `Ready`. `LastRun`/`NextRun` aparecem após o primeiro disparo.

Conferir nos logs:
- `logs\task_scheduler_wrapper.log` — recebeu nova entrada (smoke do `.bat`).
- `logs\scheduler.log` — ganhou bloco "Scheduler: iniciando pipeline... → ... → Scheduler: pipeline concluido".

Aguardar próximo disparo natural (13:00 ou 17:00) para confirmar trigger automático funciona.

(Opcional) Reboot do PC e re-conferir no próximo horário — valida que sobrevive a restart.

## Passo 5 — Documentar (opcional, recomendado)

Adicionar nota em [`CLAUDE.md`](../CLAUDE.md) na seção "Scheduler" indicando que a forma operacional **neste host** é via Windows Scheduled Task (não `--schedule` em foreground), apontando para o `.bat` e os nomes das tasks. Evita que uma sessão futura tente reiniciar o `BlockingScheduler` achando que ele é o canal de produção.

Sugestão de bloco a adicionar:

> **Operação em produção (PC de casa, 2026-04-29 em diante)**: o scheduler é disparado por 3 Windows Scheduled Tasks (`UFPR_Pipeline_08h/13h/17h`) que invocam `scripts\run_scheduled_once.bat`. **Não** rodar `python -m ufpr_automation --schedule` em foreground como antes — fragilidade do `BlockingScheduler` causou o gap de 27/04 a 29/04. Para gerenciar: `schtasks /query /tn "UFPR_Pipeline_*"`, `schtasks /run /tn "UFPR_Pipeline_08h"`, `schtasks /change /tn ... /rp <nova_senha>` (após troca de senha do Windows).

## Arquivos críticos

- [`scheduler.py`](scheduler.py) — `run_scheduled_pipeline()` linha 33; **não modificado**, apenas invocado via `--schedule --once`.
- [`cli/commands.py:291-299`](cli/commands.py) — handler do `--schedule --once`; **não modificado**.
- [`.env`](.env) — credenciais; precisa ser encontrado a partir do cwd (por isso o `cd /d` no `.bat`).
- **NOVO**: `<RAIZ>\scripts\run_scheduled_once.bat` — wrapper.
- **NOVO**: 3 Windows Scheduled Tasks fora do filesystem.

## Riscos e pontos de atenção

- **Senha do usuário Windows**: se mudar depois, as 3 tasks param silenciosamente. Atualizar com `schtasks /change /tn "UFPR_Pipeline_08h" /rp <nova>` (e nas outras duas).
- **Caminho do `.env`**: `config/settings.py` procura no cwd; o `cd /d "<RAIZ>"` no `.bat` é obrigatório (a task roda de `C:\Windows\System32` por padrão, sem o `cd` falharia).
- **Lock concorrente**: se um ciclo durar >5h (improvável — histórico mostra 2-3 min), o próximo trigger pode rodar em paralelo. APScheduler tinha `misfire_grace_time=3600` para isso, mas Task Scheduler não. Mitigação se necessário: nas Properties da task → Settings → "Do not start a new instance".
- **Backlog de ~5 ciclos**: pode resultar em 30+ emails na corrida do Passo 3 (pipeline aguenta — historicamente corre 10 emails em ~2 min).
- **Diferença de paths entre PCs**: `<RAIZ>` e `<USUARIO_WINDOWS>` precisam ser substituídos pelos valores reais do PC de casa. Não copiar literalmente os comandos.

## Quando terminar

Depois que as 3 tasks estiverem registradas e a corrida do Passo 3 confirmar funcionamento:
- Apagar este arquivo? **Não** — manter como histórico do diagnóstico e referência operacional. Pode mover para `docs/` se preferir, ou deixar na raiz do `ufpr_automation/` junto com `PLANO_EXPANSAO_TIER0_E_ROLE.md`.
- Considerar marcar como "concluído" editando o cabeçalho `> **Status**: pendente` para `> **Status**: implementado em <data>`.
