"""agent_sdk — thin wrapper for Claude Code CLI one-shot invocations.

All offline automations (Intent Drafter, Feedback Chat, Classification
Debugger, etc.) go through :func:`runner.run_claude_oneshot` so audit,
retries, and output parsing are uniform.

See SDD_CLAUDE_CODE_AUTOMATIONS.md for the full spec.
"""
