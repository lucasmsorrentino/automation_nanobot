---
description: Run the UFPR automation pipeline once (scheduled --once)
allowed-tools: Bash(python -m ufpr_automation --schedule --once)
---

Run the UFPR email automation pipeline one time against Gmail, using the
current `.env` config. Don't modify anything; just execute and report the
summary (emails processed, categories seen, drafts saved).

!`python -m ufpr_automation --schedule --once`
