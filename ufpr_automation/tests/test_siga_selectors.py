"""Tests for the SIGA selectors manifest loader.

Mirrors the structural guarantees of ``test_sei_writer`` for the SEI
side: the loader must fail fast on missing/malformed manifests, must
validate schema version, and must refuse any manifest that sneaks a
write-op selector past the read-only policy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ufpr_automation.siga import selectors as sel

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "siga_selectors.example.yaml"


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts with a clean lru_cache."""
    sel.clear_cache()
    yield
    sel.clear_cache()


@pytest.fixture
def use_example_manifest(monkeypatch):
    """Point the loader at the canonical example fixture."""
    monkeypatch.setenv("SIGA_SELECTORS_PATH", str(FIXTURE))


class TestManifestPathResolution:
    def test_env_override_takes_precedence(self, tmp_path, monkeypatch):
        custom = tmp_path / "custom_selectors.yaml"
        custom.write_text("meta: {schema_version: 1}\n", encoding="utf-8")
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(custom))
        assert sel._manifest_path() == custom

    def test_no_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("SIGA_SELECTORS_PATH", raising=False)
        path = sel._manifest_path()
        # Either resolves to .../latest/... or to a timestamped candidate
        # under procedures_data/siga_capture. The exact path depends on
        # the developer's local state; we only check the parent tree.
        assert "siga_capture" in path.as_posix()

    def test_has_manifest_false_without_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(tmp_path / "nope.yaml"))
        assert sel.has_manifest() is False

    def test_has_manifest_true_with_fixture(self, use_example_manifest):
        assert sel.has_manifest() is True


class TestLoaderHappyPath:
    def test_loads_example_fixture(self, use_example_manifest):
        data = sel.get_selectors()
        assert data["meta"]["schema_version"] == 1
        assert "login" in data
        assert "screens" in data
        assert "student_search" in data["screens"]

    def test_get_screen(self, use_example_manifest):
        search = sel.get_screen("student_search")
        assert search["fields"]["grr_input"]["selector"] == "input[name='matricula']"

    def test_get_field(self, use_example_manifest):
        nome = sel.get_field("student_detail", "nome")
        assert nome["selector"] == "#dados_aluno_nome"
        assert nome["extract"] == "text"

    def test_get_navigation(self, use_example_manifest):
        nav = sel.get_navigation("student_search")
        assert nav["url_hint"] == "/consulta/aluno"

    def test_get_login(self, use_example_manifest):
        login = sel.get_login()
        assert login["fields"]["username"]["selector"] == "#login"
        assert login["logged_in_indicator"]["selector"].startswith("a:has-text(")

    def test_loader_is_cached(self, use_example_manifest):
        a = sel.get_selectors()
        b = sel.get_selectors()
        assert a is b  # same object — lru_cache hit

    def test_clear_cache_forces_reload(self, use_example_manifest):
        a = sel.get_selectors()
        sel.clear_cache()
        b = sel.get_selectors()
        assert a is not b


class TestLoaderErrorPaths:
    def test_missing_file_raises_with_guidance(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(tmp_path / "nope.yaml"))
        with pytest.raises(sel.SIGASelectorsError, match="siga_selectors.yaml not found"):
            sel.get_selectors()

    def test_malformed_yaml_raises(self, tmp_path, monkeypatch):
        bad = tmp_path / "bad.yaml"
        bad.write_text("key: [unclosed\n", encoding="utf-8")
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(bad))
        with pytest.raises(sel.SIGASelectorsError, match="malformed"):
            sel.get_selectors()

    def test_non_mapping_top_level_raises(self, tmp_path, monkeypatch):
        bad = tmp_path / "list.yaml"
        bad.write_text("- just\n- a\n- list\n", encoding="utf-8")
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(bad))
        with pytest.raises(sel.SIGASelectorsError, match="must be a mapping"):
            sel.get_selectors()

    def test_missing_required_keys_raises(self, tmp_path, monkeypatch):
        bad = tmp_path / "incomplete.yaml"
        bad.write_text("meta:\n  schema_version: 1\n", encoding="utf-8")
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(bad))
        with pytest.raises(sel.SIGASelectorsError, match="missing required top-level keys"):
            sel.get_selectors()

    def test_wrong_schema_version_raises(self, tmp_path, monkeypatch, use_example_manifest):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        data["meta"]["schema_version"] = 99
        bad = tmp_path / "wrong_ver.yaml"
        bad.write_text(yaml.safe_dump(data), encoding="utf-8")
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(bad))
        sel.clear_cache()
        with pytest.raises(sel.SIGASelectorsError, match="schema_version"):
            sel.get_selectors()

    def test_unknown_screen_raises(self, use_example_manifest):
        with pytest.raises(sel.SIGASelectorsError, match="unknown screen"):
            sel.get_screen("nonexistent")

    def test_unknown_field_raises(self, use_example_manifest):
        with pytest.raises(sel.SIGASelectorsError, match="unknown field"):
            sel.get_field("student_search", "does_not_exist")

    def test_unknown_navigation_raises(self, use_example_manifest):
        with pytest.raises(sel.SIGASelectorsError, match="unknown navigation"):
            sel.get_navigation("does_not_exist")


class TestForbiddenSelectorPolicy:
    """SIGA is read-only by policy. A manifest that sneaks a write-op
    selector past the loader is a safety regression; these tests are
    the architectural guard."""

    @pytest.mark.parametrize(
        "forbidden",
        [
            "#btnSalvar",
            "#btnAlterar",
            "text=Matricular",
            "text=Excluir",
            "text=Inserir",
            "button:has-text('Salvar')",  # contains forbidden substring
        ],
    )
    def test_rejects_forbidden_selector_in_screen(self, tmp_path, monkeypatch, forbidden):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        data["screens"]["student_search"]["submit_selector"] = forbidden
        bad = tmp_path / "poisoned.yaml"
        bad.write_text(yaml.safe_dump(data), encoding="utf-8")
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(bad))
        sel.clear_cache()
        with pytest.raises(sel.SIGASelectorsError, match="read-only policy"):
            sel.get_selectors()

    def test_rejects_forbidden_selector_nested_in_field(self, tmp_path, monkeypatch):
        data = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
        data["screens"]["student_detail"]["fields"]["nome"]["selector"] = "#btnSalvar"
        bad = tmp_path / "nested.yaml"
        bad.write_text(yaml.safe_dump(data), encoding="utf-8")
        monkeypatch.setenv("SIGA_SELECTORS_PATH", str(bad))
        sel.clear_cache()
        with pytest.raises(sel.SIGASelectorsError, match="read-only policy"):
            sel.get_selectors()

    def test_allows_forbidden_selector_in_documentation_section(self, use_example_manifest):
        """The dedicated ``forbidden_selectors`` section lists them by design
        — listing ≠ using."""
        data = sel.get_selectors()
        assert "#btnSalvar" in data["forbidden_selectors"]

    def test_is_forbidden_helper(self):
        assert sel._is_forbidden("#btnSalvar") is True
        assert sel._is_forbidden("button.SalvarAlteracoes") is True
        assert sel._is_forbidden("#dados_aluno_nome") is False
        assert sel._is_forbidden("a:has-text('Sair')") is False


class TestFixtureSanity:
    """Protect the canonical fixture from accidental rot."""

    def test_fixture_exists(self):
        assert FIXTURE.exists(), f"canonical fixture missing at {FIXTURE}"

    def test_fixture_loads_without_error(self, use_example_manifest):
        data = sel.get_selectors()
        # Spot-check the structure contract other tests depend on.
        assert set(data["screens"].keys()) >= {
            "student_search",
            "student_detail",
        }

    def test_fixture_documents_forbidden_selectors(self, use_example_manifest):
        data = sel.get_selectors()
        fb = data.get("forbidden_selectors", [])
        assert "#btnSalvar" in fb, "fixture must document forbidden selectors"
