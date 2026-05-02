"""Factory for lazy YAML selector-manifest loaders.

Both ``sei/writer_selectors.py`` and ``siga/selectors.py`` implement the
same lifecycle for a captured Playwright-selector manifest:

    1. Resolve the manifest path (env var override, default project path,
       optional fallback discovery).
    2. Lazily load + parse YAML (``yaml.safe_load``), cached via
       ``functools.lru_cache``.
    3. Validate top-level shape against a schema (optional).
    4. Recursively walk the parsed dict; for every leaf string that
       *looks like a selector* (per a caller-supplied predicate),
       check it against the caller's forbidden-token list using the
       shared :mod:`ufpr_automation._guard_selectors` helper.
    5. Expose ``clear_cache()`` for tests that swap manifests, and
       ``has_manifest()`` for callers that want to probe before raising.

This factory captures that lifecycle in ``make_loader(...)``. The two
callers keep their domain-specific bits — different default paths,
different env vars, different forbidden-token sets, different selector
predicates, different exception classes — and the factory threads
those through without flattening them.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ufpr_automation._guard_selectors import is_forbidden as _guard_is_forbidden


def make_loader(
    *,
    manifest_filename: str,
    default_path_resolver: Callable[[], Path],
    env_var: str,
    forbidden_tokens: Iterable[str],
    forbidden_skip_paths: Callable[[str], bool],
    is_selector_leaf: Callable[[str, str], bool],
    error_cls: type[Exception],
    schema_validator: Callable[[dict[str, Any], Path], None] | None = None,
    missing_manifest_hint: str = "",
    forbidden_violation_msg: str = "selectors violate forbidden-token policy",
):
    """Build the (get_selectors, clear_cache, has_manifest, validate_no_forbidden_selectors) tuple.

    Args:
        manifest_filename:
            Bare filename used in error messages (``sei_selectors.yaml``,
            ``siga_selectors.yaml``).
        default_path_resolver:
            Zero-arg callable that returns the default ``Path`` to load
            from when ``env_var`` is not set. May implement caller-specific
            fallback rules (e.g. SIGA's "latest symlink else most-recent
            timestamped subdir"). The result need not exist on disk —
            ``has_manifest`` does that check separately.
        env_var:
            Environment variable name that overrides the default path
            with an absolute path string.
        forbidden_tokens:
            Iterable of substring tokens. Any leaf selector matching
            (case-insensitive substring) any token raises ``error_cls``
            at load time.
        forbidden_skip_paths:
            Predicate ``(path) -> bool`` returning True for dotted
            manifest paths whose contents should be skipped during the
            forbidden-selector walk. Used to exclude documentation-only
            blocks (``forbidden_buttons``, ``forbidden_selectors``).
        is_selector_leaf:
            Predicate ``(path, value) -> bool`` returning True if the
            leaf at ``path`` with the given string ``value`` should be
            treated as a Playwright selector for guard purposes. Lets
            callers ignore comment fields and notes that legitimately
            mention forbidden words.
        error_cls:
            Exception class raised on every failure mode (missing file,
            malformed YAML, schema violation, forbidden selector).
            Stays caller-specific so existing ``except SelectorsError``
            and ``except SIGASelectorsError`` blocks keep working.
        schema_validator:
            Optional ``(data, path) -> None`` callable that raises
            ``error_cls`` on schema violations. Run after YAML parse,
            before the forbidden-selector walk.
        missing_manifest_hint:
            Free-form text appended to the "manifest not found" error
            so users know how to regenerate it. Empty string omits.
        forbidden_violation_msg:
            Domain-specific phrase used in the forbidden-selector error
            message (e.g. ``"selectors violate read-only policy"`` for
            SIGA). Tests grep this — keep stable per caller.

    Returns:
        ``dict`` with keys:
            ``get_selectors``: cached loader (raises ``error_cls``).
            ``clear_cache``: clears the loader's lru_cache.
            ``has_manifest``: probe — does the manifest exist on disk?
            ``manifest_path``: returns the currently active path.
            ``validate_no_forbidden_selectors``: ``(data, path) -> None``
                invariant check, exposed so external tools (e.g. the
                grounder, before persisting a candidate manifest) can
                run the same guard the loader runs.
    """

    forbidden_tuple: tuple[str, ...] = tuple(forbidden_tokens)

    def manifest_path() -> Path:
        override = os.environ.get(env_var)
        if override:
            return Path(override)
        return default_path_resolver()

    def has_manifest() -> bool:
        return manifest_path().exists()

    def validate_no_forbidden_selectors(data: dict[str, Any], path: Path) -> None:
        violations: list[str] = []

        def _walk(node: Any, loc: str) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    _walk(v, f"{loc}.{k}" if loc else str(k))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    _walk(v, f"{loc}[{i}]")
            elif isinstance(node, str):
                if forbidden_skip_paths(loc):
                    return
                if is_selector_leaf(loc, node) and _guard_is_forbidden(node, forbidden_tuple):
                    violations.append(f"{loc} = {node!r}")

        _walk(data, "")
        if violations:
            raise error_cls(
                f"{path}: {forbidden_violation_msg} (_FORBIDDEN_SELECTORS):\n"
                + "\n".join(f"  - {v}" for v in violations)
            )

    @lru_cache(maxsize=1)
    def get_selectors() -> dict[str, Any]:
        path = manifest_path()
        if not path.exists():
            hint = (" " + missing_manifest_hint) if missing_manifest_hint else ""
            raise error_cls(f"{manifest_filename} not found at {path}.{hint}")

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise error_cls(f"malformed {manifest_filename} at {path}: {e}") from e

        if not isinstance(data, dict):
            raise error_cls(
                f"{manifest_filename} at {path} must be a mapping at the top level"
            )

        if schema_validator is not None:
            schema_validator(data, path)
        validate_no_forbidden_selectors(data, path)
        return data

    def clear_cache() -> None:
        get_selectors.cache_clear()

    return {
        "get_selectors": get_selectors,
        "clear_cache": clear_cache,
        "has_manifest": has_manifest,
        "manifest_path": manifest_path,
        "validate_no_forbidden_selectors": validate_no_forbidden_selectors,
    }
