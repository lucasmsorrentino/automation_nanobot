"""Thin wrapper around ``claude -p ...`` for one-shot agent invocations.

All automations defined under ``ufpr_automation/agent_sdk/`` go through this
runner so audit, retries, and output parsing are uniform.

Constraints (from SDD_CLAUDE_CODE_AUTOMATIONS.md §1.1):
- No Anthropic API key required — uses ``claude`` CLI authenticated via Max plan
- Never called inside the online email-processing pipeline
- Audit trail in ``procedures_data/agent_sdk/<task>/<run_id>/``
- Fail-safe: if ``claude`` is missing / quota exhausted / network down, logs and
  returns a non-success result — never breaks the online pipeline

Usage::

    from ufpr_automation.agent_sdk.runner import run_claude_oneshot

    result = run_claude_oneshot(
        task="intent_drafter",
        prompt="Analyze the last 14 days of procedures.jsonl...",
        output_format="json",
        timeout_s=300,
    )
    if result.success:
        print(result.output_json)
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ufpr_automation.config import settings

logger = logging.getLogger(__name__)

AGENT_SDK_DIR = settings.PACKAGE_ROOT / "procedures_data" / "agent_sdk"


@dataclass
class ClaudeRunResult:
    """Outcome of a one-shot ``claude -p`` invocation."""

    success: bool
    task: str
    run_id: str
    started_at: str
    duration_s: float
    prompt_chars: int
    output_text: str = ""
    output_json: dict | None = None
    stderr: str = ""
    exit_code: int = 0
    artifacts: list[Path] = field(default_factory=list)
    error: str | None = None


def is_claude_available() -> bool:
    """Pre-flight check: is ``claude`` binary in PATH and responsive?"""
    try:
        proc = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def run_claude_oneshot(
    task: str,
    prompt: str,
    *,
    output_format: str = "text",
    cwd: Path | None = None,
    timeout_s: int = 600,
    extra_args: list[str] | None = None,
    dry_run: bool = False,
) -> ClaudeRunResult:
    """Run ``claude -p PROMPT`` and capture stdout/stderr.

    Args:
        task: Short task identifier (used for audit dir + logs).
        prompt: Full prompt text — passed via stdin to avoid argv limits.
        output_format: Passed as ``--output-format`` (``text`` | ``json`` |
            ``stream-json``).
        cwd: Working directory (default: project root).
        timeout_s: Kill the subprocess after N seconds.
        extra_args: Appended to the ``claude`` argv verbatim.
        dry_run: If True, log the intended invocation but do NOT call claude.

    Returns:
        :class:`ClaudeRunResult` with parsed output (JSON if applicable)
        and audit artifact paths.
    """
    run_id = uuid.uuid4().hex[:12]
    started = datetime.now(timezone.utc)
    audit_dir = AGENT_SDK_DIR / task / run_id
    audit_dir.mkdir(parents=True, exist_ok=True)

    # Audit: save prompt
    prompt_path = audit_dir / "prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    if dry_run:
        logger.info(
            "agent_sdk[%s] DRY_RUN — would invoke claude -p (prompt: %d chars)",
            task,
            len(prompt),
        )
        return ClaudeRunResult(
            success=True,
            task=task,
            run_id=run_id,
            started_at=started.isoformat(),
            duration_s=0.0,
            prompt_chars=len(prompt),
            output_text="[DRY_RUN]",
            artifacts=[prompt_path],
        )

    argv = ["claude", "-p", "-", "--output-format", output_format]
    if extra_args:
        argv.extend(extra_args)

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            input=prompt,
            text=True,
            capture_output=True,
            cwd=str(cwd or settings.PROJECT_ROOT),
            timeout=timeout_s,
            check=False,
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired:
        duration = time.monotonic() - t0
        _write_audit_row(task, run_id, started, duration, len(prompt), "text", -1, False)
        return ClaudeRunResult(
            success=False,
            task=task,
            run_id=run_id,
            started_at=started.isoformat(),
            duration_s=duration,
            prompt_chars=len(prompt),
            error=f"timeout after {timeout_s}s",
            artifacts=[prompt_path],
        )
    except FileNotFoundError:
        _write_audit_row(task, run_id, started, 0.0, len(prompt), "text", -1, False)
        return ClaudeRunResult(
            success=False,
            task=task,
            run_id=run_id,
            started_at=started.isoformat(),
            duration_s=0.0,
            prompt_chars=len(prompt),
            error="claude binary not found in PATH — run `claude /login` first",
            artifacts=[prompt_path],
        )

    duration = time.monotonic() - t0

    # Audit: save stdout + stderr
    stdout_path = audit_dir / "stdout.txt"
    stderr_path = audit_dir / "stderr.txt"
    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    # Parse JSON if requested
    output_json: dict | None = None
    if output_format == "json" and proc.returncode == 0:
        try:
            output_json = json.loads(proc.stdout)
        except json.JSONDecodeError as e:
            logger.warning("agent_sdk[%s] failed to parse JSON output: %s", task, e)

    _write_audit_row(
        task, run_id, started, duration, len(prompt),
        output_format, proc.returncode, proc.returncode == 0,
        stdout_chars=len(proc.stdout or ""),
    )

    return ClaudeRunResult(
        success=proc.returncode == 0,
        task=task,
        run_id=run_id,
        started_at=started.isoformat(),
        duration_s=duration,
        prompt_chars=len(prompt),
        output_text=proc.stdout or "",
        output_json=output_json,
        stderr=proc.stderr or "",
        exit_code=proc.returncode,
        artifacts=[prompt_path, stdout_path, stderr_path],
    )


def _write_audit_row(
    task: str,
    run_id: str,
    started: datetime,
    duration: float,
    prompt_chars: int,
    output_format: str,
    exit_code: int,
    success: bool,
    **extra: Any,
) -> None:
    """Append a JSONL row to the shared audit log."""
    audit_row = {
        "ts": started.isoformat(),
        "task": task,
        "run_id": run_id,
        "duration_s": round(duration, 2),
        "prompt_chars": prompt_chars,
        "output_format": output_format,
        "exit_code": exit_code,
        "success": success,
        **extra,
    }
    audit_log = AGENT_SDK_DIR / "audit.jsonl"
    audit_log.parent.mkdir(parents=True, exist_ok=True)
    try:
        with audit_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit_row, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.warning("agent_sdk audit write failed: %s", e)
