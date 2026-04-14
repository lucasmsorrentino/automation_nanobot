"""SIGA Grounder — turns the UFPR Aberta BLOCO 3 tutorial into a
``siga_selectors.yaml`` manifest for :mod:`ufpr_automation.siga.selectors`.

This is the SIGA analogue of the SEI selector capture sprint, but
offline: instead of driving Playwright headed against a live SIGA
session, we read the institutional tutorial the Coordination of the
course publishes via UFPR Aberta (Moodle). The tutorial walks the user
through the screens we care about (student search, enrollment detail,
active internships) and already names the buttons, tabs, and fields in
natural language. A one-shot ``claude -p`` invocation turns that into
a structured YAML manifest.

Workflow:

    1. Another agent scrapes UFPR Aberta BLOCO 3 and saves processed
       markdown to ``base_conhecimento/ufpr_aberta/``.
    2. You run ``python -m ufpr_automation.agent_sdk.siga_grounder``.
    3. Grounder discovers BLOCO 3 markdown, hashes it, builds a prompt,
       invokes ``claude -p``, validates the YAML against the schema +
       _FORBIDDEN_SELECTORS guard, and writes it to
       ``procedures_data/siga_capture/<timestamp>/siga_selectors.yaml``.
    4. A copy is placed at
       ``procedures_data/siga_capture/latest/siga_selectors.yaml`` so the
       loader finds it without env var fiddling.

Safety / idempotency:
    - The grounder is stateless regarding credentials. It never touches
      SIGA, only the local markdown + Claude CLI.
    - Idempotency: if ``base_conhecimento/ufpr_aberta/`` content hash
      matches the last successful run, the grounder exits with a
      "no changes" message unless ``--force`` is passed.
    - Validation: if Claude's output fails schema or selector-policy
      checks, the rejected YAML is kept alongside ``rejected.yaml`` in
      the audit dir for human review; no manifest is promoted.

CLI::

    python -m ufpr_automation.agent_sdk.siga_grounder
    python -m ufpr_automation.agent_sdk.siga_grounder --source path/to/bloco3.md
    python -m ufpr_automation.agent_sdk.siga_grounder --dry-run
    python -m ufpr_automation.agent_sdk.siga_grounder --force
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ufpr_automation.agent_sdk.runner import (
    ClaudeRunResult,
    is_claude_available,
    run_claude_oneshot,
)
from ufpr_automation.config import settings
from ufpr_automation.siga.selectors import (
    SIGASelectorsError,
    _validate_no_forbidden_selectors,
    _validate_schema,
    clear_cache,
)

logger = logging.getLogger(__name__)

# Where processed tutorial markdown lives (produced by the UFPR Aberta
# scraper). Grounder reads from here.
TUTORIAL_DIR = settings.PACKAGE_ROOT / "base_conhecimento" / "ufpr_aberta"

# Where the grounder emits manifests.
CAPTURE_DIR = settings.PACKAGE_ROOT / "procedures_data" / "siga_capture"

# Pointer to the most recent valid manifest — loader checks this first.
LATEST_DIR = CAPTURE_DIR / "latest"

# Pinned briefing that tells Claude what schema to produce.
BRIEFING_PATH = Path(__file__).parent / "skills" / "siga_grounder.md"

# Hash of the inputs from the last successful run (for idempotency).
HASH_FILE = CAPTURE_DIR / ".last_run_hash"


@dataclass
class GroundingResult:
    """Outcome of one grounder invocation."""

    success: bool
    reason: str
    run_id: str = ""
    manifest_path: Path | None = None
    source_files: list[Path] = field(default_factory=list)
    content_hash: str = ""
    claude_result: ClaudeRunResult | None = None
    rejected_path: Path | None = None


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------


def discover_sources(tutorial_dir: Path | None = None) -> list[Path]:
    """Return the markdown files the grounder should consume.

    Priority order (first non-empty wins):

    1. Markdown whose filename mentions SIGA (``*siga*``) or follows the
       ``bloco_3*`` naming — these are the tutorial sections that
       describe SIGA navigation. Case-insensitive.
    2. Any ``*.md`` under ``tutorial_dir`` (merges everything).

    Returns an empty list if nothing relevant is present yet.
    """
    td = tutorial_dir or TUTORIAL_DIR
    if not td.exists():
        return []

    def _is_siga_relevant(p: Path) -> bool:
        low = p.name.lower()
        return low.startswith("bloco_3") or "siga" in low

    relevant = sorted({p for p in td.glob("*.md") if _is_siga_relevant(p)})
    if relevant:
        return relevant

    return sorted(td.glob("*.md"))


def compute_source_hash(paths: list[Path], briefing_path: Path | None = None) -> str:
    """Stable SHA-256 of source markdown + briefing content.

    Lets the grounder skip work when neither the tutorial nor the
    briefing has changed since the last successful run.
    """
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.as_posix()):
        if p.exists():
            h.update(p.read_bytes())
    bp = briefing_path or BRIEFING_PATH
    if bp.exists():
        h.update(bp.read_bytes())
    return h.hexdigest()


def last_run_hash(hash_file: Path | None = None) -> str | None:
    """Read the content hash recorded by the previous successful run."""
    hf = hash_file or HASH_FILE
    if not hf.exists():
        return None
    try:
        payload = json.loads(hf.read_text(encoding="utf-8"))
        return payload.get("content_hash")
    except (json.JSONDecodeError, OSError):
        return None


def record_run_hash(
    content_hash: str,
    manifest_path: Path,
    hash_file: Path | None = None,
) -> None:
    """Persist the content hash + manifest path for next-run idempotency."""
    hf = hash_file or HASH_FILE
    hf.parent.mkdir(parents=True, exist_ok=True)
    hf.write_text(
        json.dumps(
            {
                "content_hash": content_hash,
                "manifest_path": str(manifest_path),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Prompt construction + response parsing
# ---------------------------------------------------------------------------


def _load_briefing(briefing_path: Path | None = None) -> str:
    bp = briefing_path or BRIEFING_PATH
    if not bp.exists():
        return ""
    return bp.read_text(encoding="utf-8")


def _load_sources(paths: list[Path]) -> str:
    chunks = []
    for p in paths:
        if p.exists():
            chunks.append(f"## Source: {p.name}\n\n{p.read_text(encoding='utf-8')}\n")
    return "\n".join(chunks)


def build_prompt(
    sources: list[Path],
    *,
    briefing_path: Path | None = None,
) -> str:
    """Assemble the full prompt for Claude: briefing + sources + output contract."""
    briefing = _load_briefing(briefing_path)
    source_text = _load_sources(sources)
    if not briefing:
        briefing = _DEFAULT_BRIEFING
    return (
        briefing
        + "\n\n## Tutorial material (BLOCO 3 — SIGA navigation)\n\n"
        + source_text
        + "\n\n"
        + _OUTPUT_CONTRACT
    )


_YAML_FENCE = re.compile(r"```(?:yaml|yml)?\n(.*?)```", re.DOTALL)


def extract_yaml_from_response(response: str) -> str | None:
    """Pull the first YAML fenced block out of Claude's response.

    Falls back to the full response if no fenced block is found **and**
    the text parses as a YAML **mapping** (a bare scalar like "I'm sorry"
    technically parses as YAML but is useless here, so we reject it).
    """
    m = _YAML_FENCE.search(response)
    if m:
        return m.group(1).strip()
    try:
        parsed = yaml.safe_load(response)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return response.strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_candidate(yaml_text: str) -> tuple[bool, str, dict[str, Any] | None]:
    """Check that Claude's YAML meets the loader's contract.

    Returns ``(ok, reason, parsed_dict | None)``. Exactly mirrors the
    loader's own validation so a manifest that passes here will load.
    """
    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        return False, f"malformed YAML: {e}", None
    if not isinstance(data, dict):
        return False, "top-level YAML must be a mapping", None
    synthetic_path = Path("<candidate>")
    try:
        _validate_schema(data, synthetic_path)
        _validate_no_forbidden_selectors(data, synthetic_path)
    except SIGASelectorsError as e:
        return False, str(e), data
    # Minimum viability: at least one screen with at least one field.
    screens = data.get("screens") or {}
    if not screens:
        return False, "manifest has no 'screens' entries", data
    if not any((s.get("fields") or {}) for s in screens.values()):
        return False, "no screen has any 'fields' — would be useless to callers", data
    return True, "ok", data


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_candidate(
    yaml_text: str,
    run_id: str,
    *,
    capture_dir: Path | None = None,
) -> Path:
    """Atomically write a validated manifest to its timestamped dir and
    refresh ``latest/``.

    Returns the path of the written manifest.
    """
    cd = capture_dir or CAPTURE_DIR
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_dir = cd / f"{ts}_{run_id}"
    target_dir.mkdir(parents=True, exist_ok=True)

    target = target_dir / "siga_selectors.yaml"
    tmp = target.with_suffix(".yaml.tmp")
    tmp.write_text(yaml_text, encoding="utf-8")
    tmp.replace(target)

    # Refresh latest/. On Windows we can't rely on symlinks, so copy.
    latest = cd / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    latest_target = latest / "siga_selectors.yaml"
    tmp_latest = latest_target.with_suffix(".yaml.tmp")
    tmp_latest.write_text(yaml_text, encoding="utf-8")
    tmp_latest.replace(latest_target)

    # Drop a pointer file so humans can find the origin.
    (latest / "SOURCE.txt").write_text(target.as_posix(), encoding="utf-8")

    # Force loader to pick up the new manifest.
    clear_cache()
    return target


def write_rejected(
    yaml_text: str,
    reason: str,
    run_id: str,
    *,
    capture_dir: Path | None = None,
) -> Path:
    """Park a failed candidate for human review; never overwrites a
    previously accepted manifest."""
    cd = capture_dir or CAPTURE_DIR
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_dir = cd / f"{ts}_{run_id}_REJECTED"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "rejected.yaml").write_text(yaml_text, encoding="utf-8")
    (target_dir / "reason.txt").write_text(reason, encoding="utf-8")
    return target_dir


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run(
    *,
    source_override: Path | None = None,
    tutorial_dir: Path | None = None,
    briefing_path: Path | None = None,
    capture_dir: Path | None = None,
    hash_file: Path | None = None,
    dry_run: bool = False,
    force: bool = False,
    timeout_s: int = 600,
) -> GroundingResult:
    """Run one grounding pass. Returns a :class:`GroundingResult`."""
    if source_override:
        sources = [source_override]
    else:
        sources = discover_sources(tutorial_dir)

    if not sources:
        return GroundingResult(
            success=False,
            reason=(
                "no tutorial sources found. Expected markdown in "
                f"{(tutorial_dir or TUTORIAL_DIR).as_posix()}. "
                "Run the UFPR Aberta BLOCO 3 scraper first."
            ),
            source_files=[],
        )

    content_hash = compute_source_hash(sources, briefing_path=briefing_path)
    prev_hash = last_run_hash(hash_file)
    if not force and prev_hash == content_hash:
        return GroundingResult(
            success=True,
            reason="source content unchanged since last run (use --force to re-run)",
            source_files=sources,
            content_hash=content_hash,
        )

    prompt = build_prompt(sources, briefing_path=briefing_path)

    if dry_run:
        logger.info("siga_grounder: DRY_RUN — prompt prepared (%d chars)", len(prompt))
        return GroundingResult(
            success=True,
            reason=f"dry_run — prompt prepared with {len(prompt)} chars",
            source_files=sources,
            content_hash=content_hash,
        )

    if not is_claude_available():
        return GroundingResult(
            success=False,
            reason="claude CLI not available. Run `claude /login` first.",
            source_files=sources,
            content_hash=content_hash,
        )

    cr = run_claude_oneshot(
        task="siga_grounder",
        prompt=prompt,
        output_format="text",
        timeout_s=timeout_s,
    )

    if not cr.success:
        return GroundingResult(
            success=False,
            reason=f"claude invocation failed: {cr.error or cr.stderr[:200]}",
            run_id=cr.run_id,
            source_files=sources,
            content_hash=content_hash,
            claude_result=cr,
        )

    yaml_text = extract_yaml_from_response(cr.output_text)
    if not yaml_text:
        rej = write_rejected(
            cr.output_text, "no YAML block found in response", cr.run_id,
            capture_dir=capture_dir,
        )
        return GroundingResult(
            success=False,
            reason="Claude returned no parseable YAML — see rejected.yaml",
            run_id=cr.run_id,
            source_files=sources,
            content_hash=content_hash,
            claude_result=cr,
            rejected_path=rej,
        )

    ok, reason, _data = validate_candidate(yaml_text)
    if not ok:
        rej = write_rejected(yaml_text, reason, cr.run_id, capture_dir=capture_dir)
        return GroundingResult(
            success=False,
            reason=f"candidate rejected: {reason}",
            run_id=cr.run_id,
            source_files=sources,
            content_hash=content_hash,
            claude_result=cr,
            rejected_path=rej,
        )

    manifest = write_candidate(yaml_text, cr.run_id, capture_dir=capture_dir)
    record_run_hash(content_hash, manifest, hash_file)

    return GroundingResult(
        success=True,
        reason=f"manifest written to {manifest.as_posix()}",
        run_id=cr.run_id,
        manifest_path=manifest,
        source_files=sources,
        content_hash=content_hash,
        claude_result=cr,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="siga_grounder",
        description="Produce siga_selectors.yaml from UFPR Aberta BLOCO 3 tutorial.",
    )
    p.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Explicit markdown path to ground from (overrides auto-discovery).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the prompt but do not call Claude.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Ignore the idempotency hash and re-run even if inputs are unchanged.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Seconds to wait for Claude (default 600).",
    )
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    result = run(
        source_override=args.source,
        dry_run=args.dry_run,
        force=args.force,
        timeout_s=args.timeout,
    )

    if result.success:
        print(f"[OK] {result.reason}")
        if result.manifest_path:
            print(f"     manifest: {result.manifest_path.as_posix()}")
        return 0
    else:
        print(f"[FAIL] {result.reason}", file=sys.stderr)
        if result.rejected_path:
            print(f"       rejected output: {result.rejected_path.as_posix()}",
                  file=sys.stderr)
        return 1


# ---------------------------------------------------------------------------
# Embedded fallback briefing (used if skills/siga_grounder.md is absent)
# ---------------------------------------------------------------------------


_DEFAULT_BRIEFING = """You are the SIGA Grounder. Your job is to read the provided UFPR Aberta \
tutorial (BLOCO 3 — SIGA navigation, maintained by the course coordination) \
and emit a single YAML manifest that the ufpr_automation pipeline can load \
to drive Playwright against SIGA in READ-ONLY mode.

SIGA is the academic record system at UFPR. We consult it to validate \
internship eligibility. WE NEVER WRITE TO SIGA. Any selector whose text \
or id contains action verbs like Salvar / Alterar / Excluir / Matricular \
/ Cadastrar / Confirmar must be OMITTED or placed inside the dedicated \
`forbidden_selectors` section (which documents what must never be clicked).

Extract, in order of priority:

1. The login flow (url, username field, password field, submit button,
   post-login indicator).
2. Navigation from the home screen to the student search (menu clicks +
   any URL hint visible in the tutorial).
3. The student search form and the expected result page structure.
4. The student detail page — selectors for nome, curso, situação / status,
   carga horária matriculada, and any other fields named in the tutorial.
5. Historico / Enrollment history screen — list of disciplines, grade
   letters, reprovação-por-falta highlighting if described.
6. Active internships screen — list of concedentes, hours per week.

If the tutorial does not describe a given screen, OMIT that screen rather \
than guessing. A smaller, correct manifest is more useful than a larger \
speculative one.
"""


_OUTPUT_CONTRACT = """## Output contract

Respond with exactly ONE YAML fenced block and nothing else. The YAML
must conform to the schema documented in `siga/SELECTORS_SCHEMA.md` and must load via `ufpr_automation.siga.selectors.get_selectors()`
without raising. Use `schema_version: 1`.

Rules recap:
- Top-level keys required: `meta`, `login`, `screens`.
- `meta.schema_version` must be `1`.
- Every selector must be a concrete Playwright-compatible string
  (id `#...`, text `text=...`, css `button[name=...]`, etc.).
- Do NOT include any selector that matches write-op verbs
  (Salvar, Alterar, Excluir, Matricular, Cadastrar, Confirmar, etc.)
  outside the dedicated `forbidden_selectors: [...]` documentation list.
- If you are unsure of a selector, OMIT that field — do not guess.

Begin the YAML with `meta:`.
"""


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
