"""Tests for agent_sdk/siga_grounder.py.

The grounder orchestrates discovery → hashing → prompt build →
Claude invocation → YAML extraction → validation → write. All
external dependencies (``run_claude_oneshot``, ``is_claude_available``,
Claude itself) are patched in these tests so the suite stays offline.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from ufpr_automation.agent_sdk import siga_grounder as sg
from ufpr_automation.agent_sdk.runner import ClaudeRunResult


FIXTURE_EXAMPLE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "siga_selectors.example.yaml"
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tutorial_dir(tmp_path):
    """Empty directory to receive fake tutorial markdown."""
    d = tmp_path / "ufpr_aberta"
    d.mkdir()
    return d


@pytest.fixture
def capture_dir(tmp_path):
    d = tmp_path / "siga_capture"
    d.mkdir()
    return d


@pytest.fixture
def hash_file(tmp_path):
    return tmp_path / ".last_run_hash"


@pytest.fixture
def briefing_path(tmp_path):
    b = tmp_path / "briefing.md"
    b.write_text("BRIEFING STUB.\n", encoding="utf-8")
    return b


@pytest.fixture
def example_yaml_text():
    return FIXTURE_EXAMPLE.read_text(encoding="utf-8")


@pytest.fixture
def populated_tutorial(tutorial_dir):
    (tutorial_dir / "BLOCO_3_siga_navigation.md").write_text(
        "# BLOCO 3\n\nLogin URL: /sistemasweb/login. Campo login = #login, senha = #senha.\n"
        "Após login, menu Consulta → Alunos leva a um formulário com input name='matricula'.\n"
        "Na página do aluno: #dados_aluno_nome, #dados_aluno_curso, #dados_aluno_situacao.\n",
        encoding="utf-8",
    )
    return tutorial_dir


# ---------------------------------------------------------------------------
# Source discovery
# ---------------------------------------------------------------------------


class TestDiscoverSources:
    def test_returns_empty_when_dir_missing(self, tmp_path):
        assert sg.discover_sources(tmp_path / "nope") == []

    def test_prefers_bloco3_over_others(self, tutorial_dir):
        (tutorial_dir / "BLOCO_1.md").write_text("one", encoding="utf-8")
        (tutorial_dir / "BLOCO_3_siga.md").write_text("three", encoding="utf-8")
        (tutorial_dir / "BLOCO_4.md").write_text("four", encoding="utf-8")
        out = sg.discover_sources(tutorial_dir)
        assert len(out) == 1
        assert "BLOCO_3" in out[0].name

    def test_lowercase_bloco3_also_matches(self, tutorial_dir):
        (tutorial_dir / "bloco_3_navigation.md").write_text("x", encoding="utf-8")
        out = sg.discover_sources(tutorial_dir)
        assert len(out) == 1

    def test_picks_up_siga_named_files(self, tutorial_dir):
        """Real-world: tutorial files may be named semantically
        (e.g. bloco_siga_secretarias.md) instead of bloco_3*."""
        (tutorial_dir / "bloco_alunos.md").write_text("off-topic", encoding="utf-8")
        (tutorial_dir / "bloco_siga_secretarias.md").write_text(
            "SIGA content", encoding="utf-8"
        )
        (tutorial_dir / "FLUXO_GERAL.md").write_text("flow", encoding="utf-8")
        out = sg.discover_sources(tutorial_dir)
        names = [p.name for p in out]
        assert names == ["bloco_siga_secretarias.md"]

    def test_combines_bloco3_and_siga_named(self, tutorial_dir):
        (tutorial_dir / "bloco_3_intro.md").write_text("x", encoding="utf-8")
        (tutorial_dir / "bloco_siga_flow.md").write_text("y", encoding="utf-8")
        (tutorial_dir / "bloco_outros.md").write_text("z", encoding="utf-8")
        out = sg.discover_sources(tutorial_dir)
        assert len(out) == 2
        assert {p.name for p in out} == {"bloco_3_intro.md", "bloco_siga_flow.md"}

    def test_falls_back_to_all_md_when_nothing_relevant(self, tutorial_dir):
        (tutorial_dir / "BLOCO_1.md").write_text("one", encoding="utf-8")
        (tutorial_dir / "BLOCO_2.md").write_text("two", encoding="utf-8")
        out = sg.discover_sources(tutorial_dir)
        assert len(out) == 2


# ---------------------------------------------------------------------------
# Hashing + idempotency
# ---------------------------------------------------------------------------


class TestHashing:
    def test_hash_stable_across_calls(self, populated_tutorial, briefing_path):
        srcs = sg.discover_sources(populated_tutorial)
        h1 = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        h2 = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_hash_changes_when_source_changes(
        self, populated_tutorial, briefing_path
    ):
        srcs = sg.discover_sources(populated_tutorial)
        h1 = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        (populated_tutorial / "BLOCO_3_siga_navigation.md").write_text(
            "# BLOCO 3\n\nDIFFERENT CONTENT.\n", encoding="utf-8"
        )
        h2 = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        assert h1 != h2

    def test_hash_changes_when_briefing_changes(
        self, populated_tutorial, briefing_path
    ):
        srcs = sg.discover_sources(populated_tutorial)
        h1 = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        briefing_path.write_text("NEW BRIEFING", encoding="utf-8")
        h2 = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        assert h1 != h2

    def test_last_run_hash_round_trip(self, hash_file, tmp_path):
        manifest = tmp_path / "manifest.yaml"
        manifest.write_text("x", encoding="utf-8")
        sg.record_run_hash("abc123", manifest, hash_file=hash_file)
        assert sg.last_run_hash(hash_file=hash_file) == "abc123"

    def test_last_run_hash_returns_none_when_missing(self, tmp_path):
        assert sg.last_run_hash(hash_file=tmp_path / "nope.json") is None


# ---------------------------------------------------------------------------
# YAML extraction + validation
# ---------------------------------------------------------------------------


class TestYamlExtraction:
    def test_extracts_fenced_yaml_block(self):
        response = (
            "Some preamble.\n```yaml\nmeta:\n  schema_version: 1\n```\nPostscript."
        )
        out = sg.extract_yaml_from_response(response)
        assert out is not None
        assert "schema_version: 1" in out

    def test_accepts_bare_yaml_without_fence(self):
        response = "meta:\n  schema_version: 1\nkey: value\n"
        out = sg.extract_yaml_from_response(response)
        assert out is not None
        assert out.startswith("meta:")

    def test_returns_none_on_garbage(self):
        assert sg.extract_yaml_from_response("definitely not yaml: [unclosed") is None

    def test_fence_without_language_tag_ok(self):
        response = "```\nmeta:\n  schema_version: 1\n```\n"
        out = sg.extract_yaml_from_response(response)
        assert out is not None


class TestValidateCandidate:
    def test_happy_path_using_fixture_example(self, example_yaml_text):
        ok, reason, data = sg.validate_candidate(example_yaml_text)
        assert ok, reason
        assert data is not None
        assert data["meta"]["schema_version"] == 1

    def test_rejects_missing_screens(self):
        yml = (
            "meta:\n  schema_version: 1\nlogin:\n  url: /\n  fields: {}\n  submit: {}\nscreens: {}\n"
        )
        ok, reason, _data = sg.validate_candidate(yml)
        assert not ok
        assert "screens" in reason

    def test_rejects_empty_fields_on_every_screen(self):
        yml = (
            "meta:\n  schema_version: 1\nlogin:\n  url: /\n  fields: {}\n  submit: {}\n"
            "screens:\n  s:\n    description: empty\n"
        )
        ok, reason, _data = sg.validate_candidate(yml)
        assert not ok
        assert "fields" in reason

    def test_rejects_forbidden_selector(self, example_yaml_text):
        data = yaml.safe_load(example_yaml_text)
        data["screens"]["student_search"]["submit_selector"] = "#btnSalvar"
        ok, reason, _data = sg.validate_candidate(yaml.safe_dump(data))
        assert not ok
        assert "read-only" in reason.lower() or "forbidden" in reason.lower()

    def test_rejects_wrong_schema_version(self, example_yaml_text):
        data = yaml.safe_load(example_yaml_text)
        data["meta"]["schema_version"] = 2
        ok, reason, _data = sg.validate_candidate(yaml.safe_dump(data))
        assert not ok
        assert "schema_version" in reason


# ---------------------------------------------------------------------------
# Write paths
# ---------------------------------------------------------------------------


class TestWriteCandidate:
    def test_writes_timestamped_file_and_updates_latest(
        self, capture_dir, example_yaml_text
    ):
        manifest = sg.write_candidate(example_yaml_text, "testrun", capture_dir=capture_dir)
        assert manifest.exists()
        assert manifest.name == "siga_selectors.yaml"
        assert "testrun" in manifest.parent.name

        latest = capture_dir / "latest" / "siga_selectors.yaml"
        assert latest.exists()
        assert latest.read_text(encoding="utf-8") == example_yaml_text

        source_ptr = capture_dir / "latest" / "SOURCE.txt"
        assert source_ptr.exists()
        assert manifest.as_posix() in source_ptr.read_text(encoding="utf-8")

    def test_write_rejected_keeps_failed_output(self, capture_dir):
        rej_dir = sg.write_rejected(
            "bad yaml :",
            "test reason",
            "badrun",
            capture_dir=capture_dir,
        )
        assert "REJECTED" in rej_dir.name
        assert (rej_dir / "rejected.yaml").read_text(encoding="utf-8") == "bad yaml :"
        assert (rej_dir / "reason.txt").read_text(encoding="utf-8") == "test reason"


# ---------------------------------------------------------------------------
# run() orchestrator
# ---------------------------------------------------------------------------


class TestRunOrchestrator:
    def test_exits_early_when_no_sources(self, tutorial_dir, capture_dir, hash_file):
        result = sg.run(
            tutorial_dir=tutorial_dir,
            capture_dir=capture_dir,
            hash_file=hash_file,
        )
        assert not result.success
        assert "no tutorial sources" in result.reason.lower()

    def test_idempotency_skips_when_hash_unchanged(
        self, populated_tutorial, capture_dir, hash_file, briefing_path
    ):
        srcs = sg.discover_sources(populated_tutorial)
        h = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        sg.record_run_hash(h, capture_dir / "fake_manifest.yaml", hash_file=hash_file)

        result = sg.run(
            tutorial_dir=populated_tutorial,
            briefing_path=briefing_path,
            capture_dir=capture_dir,
            hash_file=hash_file,
        )
        assert result.success
        assert "unchanged" in result.reason.lower()

    def test_force_ignores_idempotency(
        self, populated_tutorial, capture_dir, hash_file, briefing_path
    ):
        srcs = sg.discover_sources(populated_tutorial)
        h = sg.compute_source_hash(srcs, briefing_path=briefing_path)
        sg.record_run_hash(h, capture_dir / "fake_manifest.yaml", hash_file=hash_file)

        result = sg.run(
            tutorial_dir=populated_tutorial,
            briefing_path=briefing_path,
            capture_dir=capture_dir,
            hash_file=hash_file,
            force=True,
            dry_run=True,  # don't actually call claude
        )
        assert result.success
        assert "dry_run" in result.reason.lower()

    def test_dry_run_does_not_call_claude(
        self, populated_tutorial, capture_dir, hash_file, briefing_path
    ):
        with patch("ufpr_automation.agent_sdk.siga_grounder.run_claude_oneshot") as m:
            result = sg.run(
                tutorial_dir=populated_tutorial,
                briefing_path=briefing_path,
                capture_dir=capture_dir,
                hash_file=hash_file,
                dry_run=True,
            )
        assert result.success
        m.assert_not_called()

    def test_fails_gracefully_when_claude_unavailable(
        self, populated_tutorial, capture_dir, hash_file, briefing_path
    ):
        with patch(
            "ufpr_automation.agent_sdk.siga_grounder.is_claude_available",
            return_value=False,
        ):
            result = sg.run(
                tutorial_dir=populated_tutorial,
                briefing_path=briefing_path,
                capture_dir=capture_dir,
                hash_file=hash_file,
            )
        assert not result.success
        assert "claude cli not available" in result.reason.lower()

    def test_happy_path_writes_manifest(
        self, populated_tutorial, capture_dir, hash_file, briefing_path,
        example_yaml_text,
    ):
        fake_result = ClaudeRunResult(
            success=True,
            task="siga_grounder",
            run_id="happy1234",
            started_at="2026-04-14T00:00:00Z",
            duration_s=1.0,
            prompt_chars=100,
            output_text=f"```yaml\n{example_yaml_text}\n```",
        )
        with patch(
            "ufpr_automation.agent_sdk.siga_grounder.is_claude_available",
            return_value=True,
        ), patch(
            "ufpr_automation.agent_sdk.siga_grounder.run_claude_oneshot",
            return_value=fake_result,
        ):
            result = sg.run(
                tutorial_dir=populated_tutorial,
                briefing_path=briefing_path,
                capture_dir=capture_dir,
                hash_file=hash_file,
            )

        assert result.success, result.reason
        assert result.manifest_path is not None
        assert result.manifest_path.exists()
        assert (capture_dir / "latest" / "siga_selectors.yaml").exists()
        assert sg.last_run_hash(hash_file=hash_file) == result.content_hash

    def test_rejected_output_parked_on_validation_failure(
        self, populated_tutorial, capture_dir, hash_file, briefing_path,
        example_yaml_text,
    ):
        bad_yaml = yaml.safe_load(example_yaml_text)
        bad_yaml["screens"]["student_search"]["submit_selector"] = "#btnSalvar"
        fake_result = ClaudeRunResult(
            success=True,
            task="siga_grounder",
            run_id="bad5678",
            started_at="2026-04-14T00:00:00Z",
            duration_s=1.0,
            prompt_chars=100,
            output_text=f"```yaml\n{yaml.safe_dump(bad_yaml)}\n```",
        )
        with patch(
            "ufpr_automation.agent_sdk.siga_grounder.is_claude_available",
            return_value=True,
        ), patch(
            "ufpr_automation.agent_sdk.siga_grounder.run_claude_oneshot",
            return_value=fake_result,
        ):
            result = sg.run(
                tutorial_dir=populated_tutorial,
                briefing_path=briefing_path,
                capture_dir=capture_dir,
                hash_file=hash_file,
            )

        assert not result.success
        assert result.rejected_path is not None
        assert result.rejected_path.exists()
        assert (result.rejected_path / "rejected.yaml").exists()
        assert (result.rejected_path / "reason.txt").exists()
        # Idempotency hash NOT recorded for rejected runs — next invocation
        # must retry.
        assert sg.last_run_hash(hash_file=hash_file) is None

    def test_no_yaml_block_parks_raw_output(
        self, populated_tutorial, capture_dir, hash_file, briefing_path,
    ):
        fake_result = ClaudeRunResult(
            success=True,
            task="siga_grounder",
            run_id="garbage",
            started_at="2026-04-14T00:00:00Z",
            duration_s=1.0,
            prompt_chars=100,
            output_text="I'm sorry, I can't comply with that request.",
        )
        with patch(
            "ufpr_automation.agent_sdk.siga_grounder.is_claude_available",
            return_value=True,
        ), patch(
            "ufpr_automation.agent_sdk.siga_grounder.run_claude_oneshot",
            return_value=fake_result,
        ):
            result = sg.run(
                tutorial_dir=populated_tutorial,
                briefing_path=briefing_path,
                capture_dir=capture_dir,
                hash_file=hash_file,
            )
        assert not result.success
        assert "no parseable yaml" in result.reason.lower()
        assert result.rejected_path is not None
