# Scripts manuais — uso pontual / debugging

Scripts deste diretório são **utilitários one-off** invocados a mão durante
debugging, manual data export ou recovery. NÃO fazem parte do pipeline
automatizado nem do scheduler — vivem aqui pra ficarem fora de `scripts/`
(que tem só os caminhos quentes: smokes, sync, captura de selectors, etc.).

| Script | O que faz | Quando usar |
|---|---|---|
| `mark_unread.py` | Marca um Message-ID Gmail específico como UNREAD via IMAP | Quando você quer reprocessar um único email no próximo run agendado |
| `mark_unread_estagios.py` | Marca como UNREAD os 3 emails Estágios mais recentes | Smoke do scheduler em batch pequeno |
| `peek_last_draft.py` | Lê (read-only) o draft Gmail mais recente — útil pra inspecionar saída do pipeline sem abrir UI | Debugging manual de saída |
| `debug_sei_login.py` | Tenta login no SEI com tracing verbose; útil quando `auto_login` falha em prod | Investigar falha de login isolada |
| `download_sei_pops.sh` | Bash legado pra baixar POPs do SEI UFPR; substituído por backlog em `G:/Meu Drive/ufpr_rag/docs/ainda_n_ingeridos/` | Histórico — não usar mais |

## Convenções

- Cada script é executável standalone (`python scripts/manual/<nome>.py`).
- Não são testados por `pytest` — riscos isolados na hora do uso.
- Para emergências de produção, prefira `scripts/reprocess_one.py` (que está em `scripts/`, fora desta pasta) — ele é o caminho oficial de "remover label `ufpr/processado` + flag Seen pra um Message-ID".

## Adicionar novo script aqui

Se um script é one-off pra você + nunca vai rodar automatizado → vem pra cá.
Se é parte de algum fluxo recorrente (smoke, sync, captura) → fica em `scripts/`.
