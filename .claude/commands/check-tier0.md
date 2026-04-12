---
description: Quick Tier 0 playbook health check — intent count + staleness
allowed-tools: Bash(python -c:*), Bash(python -m ufpr_automation.agent_sdk.procedures_staleness)
---

Run a quick health check on the Tier 0 playbook:

1. Count intents in `workspace/PROCEDURES.md`
2. List registered checkers
3. Run the staleness checker to flag outdated intents

!`python -c "from ufpr_automation.procedures.playbook import get_playbook; pb = get_playbook(); print(f'Tier 0: {len(pb.intents)} intents loaded')"`

!`python -c "from ufpr_automation.procedures.checkers import registered_checkers; print(f'Checkers: {len(registered_checkers())}'); [print(f'  - {c}') for c in registered_checkers()]"`

!`python -m ufpr_automation.agent_sdk.procedures_staleness`
