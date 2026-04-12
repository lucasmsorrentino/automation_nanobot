"""Tests for Marco V Fase 7 — Maintainer polish.

Validates that the checked-in slash commands, skill files, and project
settings.json are well-formed. These artifacts are consumed by the
interactive Claude Code CLI when the operator runs `claude` in this repo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CLAUDE_DIR = REPO_ROOT / ".claude"
COMMANDS_DIR = CLAUDE_DIR / "commands"
SETTINGS_JSON = CLAUDE_DIR / "settings.json"
SKILLS_DIR = REPO_ROOT / "ufpr_automation" / "agent_sdk" / "skills"
MAINTAINER_SKILL = SKILLS_DIR / "maintainer.md"


class TestSkillFiles:
    def test_maintainer_skill_exists(self):
        assert MAINTAINER_SKILL.exists(), (
            f"{MAINTAINER_SKILL} is missing — required by Fase 7 SDD §8.3"
        )

    def test_maintainer_skill_covers_key_topics(self):
        content = MAINTAINER_SKILL.read_text(encoding="utf-8")
        # Must mention the main automation entry points
        for keyword in [
            "python -m ufpr_automation",
            "pytest",
            "rag",
            "feedback",
            "agent_sdk",
            "TASKS.md",
        ]:
            assert keyword in content.lower() or keyword in content, (
                f"maintainer.md missing reference to '{keyword}'"
            )

    def test_feedback_chat_bootstrap_skill_exists(self):
        assert (SKILLS_DIR / "feedback_chat_bootstrap.md").exists()

    def test_intent_drafter_skill_exists(self):
        assert (SKILLS_DIR / "intent_drafter.md").exists()


class TestSlashCommands:
    EXPECTED_COMMANDS = [
        "run-pipeline-once",
        "feedback-stats",
        "check-tier0",
        "test-suite",
        "rag-query",
    ]

    def test_commands_dir_exists(self):
        assert COMMANDS_DIR.exists()

    @pytest.mark.parametrize("cmd_name", EXPECTED_COMMANDS)
    def test_command_file_exists(self, cmd_name):
        cmd_file = COMMANDS_DIR / f"{cmd_name}.md"
        assert cmd_file.exists(), f"Slash command /{cmd_name} is missing"

    @pytest.mark.parametrize("cmd_name", EXPECTED_COMMANDS)
    def test_command_has_description(self, cmd_name):
        """Each slash command must have a YAML frontmatter description."""
        cmd_file = COMMANDS_DIR / f"{cmd_name}.md"
        content = cmd_file.read_text(encoding="utf-8")
        # Frontmatter block
        match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
        assert match, f"{cmd_name}: missing YAML frontmatter"
        fm = match.group(1)
        assert "description:" in fm, f"{cmd_name}: missing 'description' in frontmatter"

    @pytest.mark.parametrize("cmd_name", EXPECTED_COMMANDS)
    def test_command_has_bash_action(self, cmd_name):
        """Each command must have at least one !`...` bash invocation."""
        cmd_file = COMMANDS_DIR / f"{cmd_name}.md"
        content = cmd_file.read_text(encoding="utf-8")
        assert re.search(r"!\s*`[^`]+`", content), (
            f"{cmd_name}: no bash action (expected !`cmd` syntax)"
        )


class TestProjectSettings:
    def test_settings_json_exists(self):
        assert SETTINGS_JSON.exists()

    def test_settings_is_valid_json(self):
        data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        assert "permissions" in data

    def test_permissions_have_allow_and_deny(self):
        data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        assert "allow" in data["permissions"]
        assert "deny" in data["permissions"]
        assert len(data["permissions"]["allow"]) > 0

    def test_deny_list_blocks_dangerous_ops(self):
        """Verify destructive ops are denied."""
        data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        deny = " ".join(data["permissions"]["deny"])
        assert "rm -rf" in deny
        assert "push --force" in deny

    def test_allow_list_covers_readonly_agent_sdk(self):
        """Verify common read-only agent_sdk commands are pre-approved."""
        data = json.loads(SETTINGS_JSON.read_text(encoding="utf-8"))
        allow = " ".join(data["permissions"]["allow"])
        assert "procedures_staleness" in allow
        assert "debug_classification" in allow
        assert "rag_auditor" in allow

    def test_no_credentials_in_settings(self):
        """Project-level settings.json must not leak credentials."""
        content = SETTINGS_JSON.read_text(encoding="utf-8")
        lower = content.lower()
        for leak in ["password", "secret", "token=", "api_key", "ghp_"]:
            assert leak not in lower, f"possible credential leak: {leak}"
