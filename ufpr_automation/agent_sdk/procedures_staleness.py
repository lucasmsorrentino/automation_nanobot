"""PROCEDURES.md Staleness Checker — detects intents misaligned with SOUL.md / checkers.

For each intent in ``workspace/PROCEDURES.md``, checks:
1. ``blocking_checks`` — all IDs must be registered in ``procedures/checkers.py``
2. ``sources`` — references to ``SOUL.md §X`` must match existing sections
3. ``last_update`` — warns if older than a configurable threshold (default 90 days)
4. ``sei_action`` + ``sei_process_type`` — if sei_action != "none", process type should
   exist in SEI_DOC_CATALOG.yaml

See ``SDD_CLAUDE_CODE_AUTOMATIONS.md §7`` for the full spec.

CLI::

    python -m ufpr_automation.agent_sdk.procedures_staleness
    python -m ufpr_automation.agent_sdk.procedures_staleness --max-age-days 60
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from ufpr_automation.config import settings
from ufpr_automation.procedures.playbook import Intent, parse_procedures_md

logger = logging.getLogger(__name__)

PROCEDURES_MD = settings.PACKAGE_ROOT / "workspace" / "PROCEDURES.md"
SOUL_MD = settings.PACKAGE_ROOT / "workspace" / "SOUL.md"
SEI_DOC_CATALOG = settings.PACKAGE_ROOT / "workspace" / "SEI_DOC_CATALOG.yaml"
REPORT_DIR = settings.PACKAGE_ROOT / "procedures_data" / "agent_sdk" / "procedures_staleness"


@dataclass
class IntentCheck:
    """Result of staleness analysis for one intent."""

    intent_name: str
    status: str  # "ok", "warning", "stale"
    issues: list[str] = field(default_factory=list)


def _load_soul_sections(path: Path | None = None) -> set[str]:
    """Extract section references from SOUL.md (e.g. '§8', '§11.2')."""
    p = path or SOUL_MD
    if not p.exists():
        return set()
    text = p.read_text(encoding="utf-8")
    sections: set[str] = set()
    for m in re.finditer(r"^#+\s+.*?(\d+(?:\.\d+)*)", text, re.MULTILINE):
        sections.add(m.group(1))
    # Also extract from ## N. or ## N — style headers
    for m in re.finditer(r"^#{1,4}\s+(\d+(?:\.\d+)*)\b", text, re.MULTILINE):
        sections.add(m.group(1))
    return sections


def _load_registered_checkers() -> set[str]:
    """Get the set of checker IDs registered in procedures/checkers.py."""
    try:
        from ufpr_automation.procedures.checkers import registered_checkers

        return set(registered_checkers())
    except Exception as e:
        logger.warning("Could not load registered checkers: %s", e)
        return set()


def _load_catalog_process_types(path: Path | None = None) -> set[str]:
    """Load process type labels from SEI_DOC_CATALOG.yaml."""
    p = path or SEI_DOC_CATALOG
    if not p.exists():
        return set()
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            types: set[str] = set()
            for entry in data.values():
                if isinstance(entry, dict):
                    pt = entry.get("tipo_processo", "")
                    if pt:
                        types.add(pt)
            return types
        return set()
    except Exception as e:
        logger.warning("Could not load SEI_DOC_CATALOG: %s", e)
        return set()


def check_intent(
    intent: Intent,
    *,
    registered_checks: set[str],
    soul_sections: set[str],
    catalog_types: set[str],
    max_age_days: int = 90,
) -> IntentCheck:
    """Analyse a single intent for staleness issues."""
    result = IntentCheck(intent_name=intent.intent_name, status="ok")

    # 1. blocking_checks — all must be registered
    for check_id in intent.blocking_checks:
        if check_id not in registered_checks:
            result.issues.append(
                f"blocking_check '{check_id}' not registered in checkers.py"
            )

    # 2. sources — SOUL.md §X references should match
    for source in intent.sources:
        m = re.search(r"SOUL\.md\s*§\s*(\d+(?:\.\d+)*)", source)
        if m:
            section_num = m.group(1)
            if soul_sections and section_num not in soul_sections:
                result.issues.append(
                    f"source '{source}' references SOUL.md §{section_num} "
                    f"which was not found in current SOUL.md"
                )

    # 3. last_update age check
    if intent.last_update:
        try:
            last = date.fromisoformat(intent.last_update)
            age_days = (date.today() - last).days
            if age_days > max_age_days:
                result.issues.append(
                    f"last_update '{intent.last_update}' is {age_days} days old "
                    f"(threshold: {max_age_days})"
                )
        except ValueError:
            result.issues.append(
                f"last_update '{intent.last_update}' is not a valid ISO date"
            )

    # 4. SEI action consistency
    if intent.sei_action != "none":
        if not intent.sei_process_type:
            result.issues.append(
                f"sei_action='{intent.sei_action}' but sei_process_type is empty"
            )
        elif catalog_types and intent.sei_process_type not in catalog_types:
            result.issues.append(
                f"sei_process_type '{intent.sei_process_type}' not found in SEI_DOC_CATALOG.yaml"
            )

    # 5. Template sanity — check for unresolved placeholders info
    if intent.template and not re.search(r"\[.+?\]", intent.template):
        if intent.required_fields:
            result.issues.append(
                "template has no [PLACEHOLDER]s but required_fields is non-empty"
            )

    # Determine overall status
    if any("not registered" in i or "not found in current" in i for i in result.issues):
        result.status = "stale"
    elif result.issues:
        result.status = "warning"

    return result


def run_staleness_check(
    *,
    procedures_path: Path | None = None,
    soul_path: Path | None = None,
    catalog_path: Path | None = None,
    max_age_days: int = 90,
    report_dir: Path | None = None,
) -> list[IntentCheck]:
    """Run staleness checks on all intents and write a report.

    Returns the list of IntentCheck results.
    """
    proc_path = procedures_path or PROCEDURES_MD
    intents = parse_procedures_md(proc_path)

    if not intents:
        logger.info("Staleness Checker: no intents found in %s", proc_path)
        return []

    registered_checks = _load_registered_checkers()
    soul_sections = _load_soul_sections(soul_path)
    catalog_types = _load_catalog_process_types(catalog_path)

    results: list[IntentCheck] = []
    for intent in intents:
        check = check_intent(
            intent,
            registered_checks=registered_checks,
            soul_sections=soul_sections,
            catalog_types=catalog_types,
            max_age_days=max_age_days,
        )
        results.append(check)

    # Write report
    out_dir = report_dir or REPORT_DIR
    run_id = uuid.uuid4().hex[:12]
    run_dir = out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    report_path = run_dir / "report.md"
    report_path.write_text(_format_report(results, max_age_days), encoding="utf-8")
    logger.info("Staleness report written to %s", report_path)

    return results


def _format_report(results: list[IntentCheck], max_age_days: int) -> str:
    """Format the staleness check results as a Markdown report."""
    lines = [
        "# PROCEDURES.md Staleness Report",
        "",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"Max age threshold: {max_age_days} days",
        f"Total intents checked: {len(results)}",
        "",
    ]

    ok = sum(1 for r in results if r.status == "ok")
    warn = sum(1 for r in results if r.status == "warning")
    stale = sum(1 for r in results if r.status == "stale")
    lines.append("| Status | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| ok | {ok} |")
    lines.append(f"| warning | {warn} |")
    lines.append(f"| stale | {stale} |")
    lines.append("")

    STATUS_ICON = {"ok": "ok", "warning": "warning", "stale": "STALE"}

    for r in results:
        icon = STATUS_ICON.get(r.status, r.status)
        lines.append(f"## [{icon}] {r.intent_name}")
        if r.issues:
            for issue in r.issues:
                lines.append(f"- {issue}")
        else:
            lines.append("- All checks passed.")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="procedures_staleness",
        description="Check PROCEDURES.md intents for staleness against SOUL.md / checkers",
    )
    parser.add_argument(
        "--max-age-days", type=int, default=90,
        help="Flag intents older than N days (default: 90)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s  %(message)s",
    )

    results = run_staleness_check(max_age_days=args.max_age_days)

    ok = sum(1 for r in results if r.status == "ok")
    warn = sum(1 for r in results if r.status == "warning")
    stale = sum(1 for r in results if r.status == "stale")

    print(f"\nResultado: {len(results)} intents checked — {ok} ok, {warn} warning, {stale} stale")
    sys.exit(1 if stale > 0 else 0)


if __name__ == "__main__":
    main()
