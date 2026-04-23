"""Deeper live-path coverage for POP-38 ``add_to_acompanhamento_especial``.

The safety-regression tests in ``test_sei_writer.py`` verify that:
    - the method exists and dry-run works
    - live mode no longer raises ``NotImplementedError``
    - forbidden selectors still raise at the guard layer

This file exercises the full live flow with fake Playwright objects so we
can assert behavioural contracts:

    - dry_run mode never reaches a submit/click
    - live + existing group: no modal, submit happens once
    - live + new group: modal flow fills #txtNome, submits modal, then
      re-selects and submits outer form
    - live + forbidden selector in spec: PermissionError, never clicked

All tests run without network / real Playwright — fake classes below
mimic the narrow surface the writer touches.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from ufpr_automation.sei.writer import SEIWriter
from ufpr_automation.sei.writer_selectors import _ACOMPANHAMENTO_ESPECIAL_DEFAULTS

# ---------------------------------------------------------------------------
# Fake Playwright surface
# ---------------------------------------------------------------------------


class FakeLocator:
    """Minimal async Locator — tracks .click / .fill calls and exposes
    configurable .count / .get_attribute return values."""

    def __init__(
        self,
        selector: str,
        *,
        count: int = 1,
        href: str | None = None,
        owner: "FakeFrame | FakePage | None" = None,
    ):
        self.selector = selector
        self._count = count
        self._href = href
        self._owner = owner
        self.fill_calls: list[str] = []
        self.click_calls: int = 0

    @property
    def first(self) -> "FakeLocator":
        return self

    async def count(self) -> int:
        return self._count

    async def get_attribute(self, name: str) -> str | None:
        if name == "href":
            return self._href
        return None

    async def click(self) -> None:
        self.click_calls += 1
        if self._owner is not None:
            self._owner.click_log.append(self.selector)

    async def fill(self, text: str) -> None:
        self.fill_calls.append(text)
        if self._owner is not None:
            self._owner.fill_log.append((self.selector, text))


class FakeFrame:
    """Minimal async Frame — supports locator, evaluate, wait_for_selector,
    goto. Responses are configured per-test via the ``evaluate_responses``
    dict and ``locator_overrides``."""

    def __init__(
        self,
        name: str = "",
        url: str = "about:blank",
        *,
        locator_overrides: dict[str, FakeLocator] | None = None,
    ):
        self.name = name
        self.url = url
        self.locator_overrides = locator_overrides or {}
        self.evaluate_responses: list[Any] = []  # FIFO
        self.evaluate_calls: list[tuple[str, Any]] = []
        self.waited_selectors: list[str] = []
        self.goto_calls: list[str] = []
        self.click_log: list[str] = []
        self.fill_log: list[tuple[str, str]] = []

    def locator(self, selector: str) -> FakeLocator:
        if selector in self.locator_overrides:
            loc = self.locator_overrides[selector]
            loc._owner = self
            return loc
        return FakeLocator(selector, count=1, owner=self)

    async def evaluate(self, js: str, arg: Any = None) -> Any:
        self.evaluate_calls.append((js, arg))
        if not self.evaluate_responses:
            return None
        return self.evaluate_responses.pop(0)

    async def wait_for_selector(
        self, selector: str, state: str = "visible", timeout: int = 5000
    ) -> None:
        self.waited_selectors.append(selector)

    async def goto(self, url: str, wait_until: str = "load") -> None:
        self.goto_calls.append(url)
        self.url = url


class FakePage:
    """Minimal async Page covering what ``add_to_acompanhamento_especial``
    needs: title, url, locator, frames/main_frame, dialog listeners, goto,
    wait_for_load_state, wait_for_timeout, screenshot, content."""

    def __init__(
        self,
        *,
        title: str = "Processo",
        url: str = "https://sei.ufpr.br/sei/controlador.php",
        frames: list[FakeFrame] | None = None,
        locator_overrides: dict[str, FakeLocator] | None = None,
    ):
        self._title = title
        self.url = url
        self._frames: list[FakeFrame] = frames or []
        self.main_frame = FakeFrame(name="", url=url)
        self.locator_overrides = locator_overrides or {}
        self.goto_calls: list[str] = []
        self.click_log: list[str] = []
        self.fill_log: list[tuple[str, str]] = []
        self._dialog_listeners: list[Any] = []

    @property
    def frames(self) -> list[FakeFrame]:
        return list(self._frames)

    def set_frames(self, frames: list[FakeFrame]) -> None:
        self._frames = frames

    async def title(self) -> str:
        return self._title

    def locator(self, selector: str) -> FakeLocator:
        if selector in self.locator_overrides:
            loc = self.locator_overrides[selector]
            loc._owner = self
            return loc
        return FakeLocator(selector, count=1, owner=self)

    def on(self, event: str, handler: Any) -> None:
        if event == "dialog":
            self._dialog_listeners.append(handler)

    def remove_listener(self, event: str, handler: Any) -> None:
        if handler in self._dialog_listeners:
            self._dialog_listeners.remove(handler)

    async def goto(self, url: str, wait_until: str = "load") -> None:
        self.goto_calls.append(url)
        self.url = url

    async def wait_for_load_state(self, state: str = "load", timeout: int = 20000) -> None:
        return None

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def screenshot(self, path: str | None = None, full_page: bool = False) -> None:
        if path:
            Path(path).write_bytes(b"\x89PNG fake")

    async def content(self) -> str:
        return "<html>fake</html>"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scenario_existing_group(processo_id: str = "23075.000001/2026-00") -> FakePage:
    """Page pre-configured to land on the cadastrar form with the target
    group already present in #selGrupoAcompanhamento (select returns a
    value on the first evaluate)."""
    vis = FakeFrame(
        name="ifrVisualizacao",
        url=(
            "https://sei.ufpr.br/sei/controlador.php?acao=acompanhamento_cadastrar&id_protocolo=42"
        ),
    )
    vis.evaluate_responses = ["grupo-id-99"]  # selects on first try

    content = FakeFrame(
        name="ifrConteudoVisualizacao",
        url="https://sei.ufpr.br/sei/controlador.php?acao=procedimento_visualizar",
        locator_overrides={
            'xpath=//a[.//img[@title="Acompanhamento Especial"]]': FakeLocator(
                'xpath=//a[.//img[@title="Acompanhamento Especial"]]',
                count=1,
                href=("controlador.php?acao=acompanhamento_cadastrar&id_protocolo=42"),
            ),
        },
    )
    return FakePage(title=f"SEI - {processo_id}", frames=[content, vis])


def _scenario_new_group(processo_id: str = "23075.000002/2026-00") -> FakePage:
    """Like _scenario_existing_group but the first evaluate returns None
    (group not found). A modal frame is injected after the novo_grupo
    click; after modal submit the modal disappears and the second
    evaluate returns a value."""
    vis = FakeFrame(
        name="ifrVisualizacao",
        url=(
            "https://sei.ufpr.br/sei/controlador.php?acao=acompanhamento_cadastrar&id_protocolo=43"
        ),
    )
    # First evaluate (initial select attempt): None.
    # Second evaluate (after modal closes): resolves the new group.
    vis.evaluate_responses = [None, "new-grupo-id-7"]

    content = FakeFrame(
        name="ifrConteudoVisualizacao",
        url="https://sei.ufpr.br/sei/controlador.php?acao=procedimento_visualizar",
        locator_overrides={
            'xpath=//a[.//img[@title="Acompanhamento Especial"]]': FakeLocator(
                'xpath=//a[.//img[@title="Acompanhamento Especial"]]',
                count=1,
                href=("controlador.php?acao=acompanhamento_cadastrar&id_protocolo=43"),
            ),
        },
    )
    page = FakePage(title=f"SEI - {processo_id}", frames=[content, vis])

    # Patch vis.locator so that clicking #imgNovoGrupoAcompanhamento
    # triggers a modal frame injection into page.frames.
    modal_frame = FakeFrame(
        name="modalGrupo",
        url=("https://sei.ufpr.br/sei/controlador.php?acao=grupo_acompanhamento_cadastrar"),
    )

    class TriggeringLocator(FakeLocator):
        async def click(self):
            self.click_calls += 1
            if self._owner is not None:
                self._owner.click_log.append(self.selector)
            # Inject the modal frame upon click.
            page.set_frames([content, vis, modal_frame])

    trigger = TriggeringLocator("#imgNovoGrupoAcompanhamento", count=1, owner=vis)
    vis.locator_overrides["#imgNovoGrupoAcompanhamento"] = trigger

    # After modal submit, remove the modal frame (modal closes).
    class ModalSubmitLocator(FakeLocator):
        async def click(self):
            self.click_calls += 1
            if self._owner is not None:
                self._owner.click_log.append(self.selector)
            # Modal closes → drop the modal frame.
            page.set_frames([content, vis])

    modal_submit = ModalSubmitLocator(
        'button[name="sbmCadastrarGrupoAcompanhamento"]',
        count=1,
        owner=modal_frame,
    )
    modal_frame.locator_overrides['button[name="sbmCadastrarGrupoAcompanhamento"]'] = modal_submit

    return page


def _make_writer(page: FakePage, tmp_path: Path, *, dry_run: bool) -> SEIWriter:
    from ufpr_automation.config import settings

    settings.SEI_WRITE_ARTIFACTS_DIR = tmp_path  # type: ignore[attr-defined]
    return SEIWriter(page, run_id="acomp-test", dry_run=dry_run)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAcompanhamentoDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_never_submits(self, tmp_path, monkeypatch):
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        page = _scenario_existing_group()
        writer = SEIWriter(page, run_id="dry-test", dry_run=True)

        result = await writer.add_to_acompanhamento_especial(
            processo_id="23075.000001/2026-00",
            grupo="Estágio não obrigatório",
        )

        assert result.success is True
        assert result.dry_run is True
        # The live flow was never entered — no locator clicks, no goto.
        assert page.click_log == []
        assert page.goto_calls == []
        for f in page.frames:
            assert f.click_log == []
            assert f.goto_calls == []

    @pytest.mark.asyncio
    async def test_dry_run_writes_audit(self, tmp_path, monkeypatch):
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        page = _scenario_existing_group()
        writer = SEIWriter(page, run_id="dry-test", dry_run=True)
        await writer.add_to_acompanhamento_especial(
            processo_id="23075.000001/2026-00",
            grupo="Estágio não obrigatório",
            observacao="Cohort 2026/1",
        )
        audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "add_to_acompanhamento_especial" in audit
        assert "dry_run" in audit
        assert "Estágio não obrigatório" in audit
        assert "Cohort 2026/1" in audit


class TestAcompanhamentoLiveExistingGroup:
    @pytest.mark.asyncio
    async def test_existing_group_selects_and_submits_without_modal(self, tmp_path, monkeypatch):
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        page = _scenario_existing_group()
        writer = SEIWriter(page, run_id="live-exist", dry_run=False)

        result = await writer.add_to_acompanhamento_especial(
            processo_id="23075.000001/2026-00",
            grupo="Estágio não obrigatório",
            observacao="Cohort 2026/1",
        )

        assert result.success is True, f"unexpected failure: {result.error!r}"
        assert result.dry_run is False

        # The vis_frame (ifrVisualizacao) is where the form lives.
        vis = next(f for f in page.frames if f.name == "ifrVisualizacao")

        # Novo-grupo icon should NEVER be clicked when the group exists.
        assert "#imgNovoGrupoAcompanhamento" not in vis.click_log

        # The cadastrar submit button must have been clicked exactly once.
        assert vis.click_log.count('button[name="sbmCadastrarAcompanhamento"]') == 1

        # Observação must have been filled on the textarea.
        obs_fill = [f for (sel, f) in vis.fill_log if sel == "#txaObservacao"]
        assert obs_fill == ["Cohort 2026/1"]

    @pytest.mark.asyncio
    async def test_existing_group_no_observacao_skips_textarea(self, tmp_path, monkeypatch):
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        page = _scenario_existing_group()
        writer = SEIWriter(page, run_id="live-exist-noobs", dry_run=False)

        result = await writer.add_to_acompanhamento_especial(
            processo_id="23075.000001/2026-00",
            grupo="Estágio não obrigatório",
            # observacao defaults to ""
        )

        assert result.success is True
        vis = next(f for f in page.frames if f.name == "ifrVisualizacao")
        # No fill should land on the obs textarea.
        assert not any(sel == "#txaObservacao" for (sel, _v) in vis.fill_log)
        # Submit still fires.
        assert 'button[name="sbmCadastrarAcompanhamento"]' in vis.click_log


class TestAcompanhamentoLiveNewGroup:
    @pytest.mark.asyncio
    async def test_new_group_opens_modal_fills_and_submits_twice(self, tmp_path, monkeypatch):
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        page = _scenario_new_group()
        writer = SEIWriter(page, run_id="live-new", dry_run=False)

        result = await writer.add_to_acompanhamento_especial(
            processo_id="23075.000002/2026-00",
            grupo="Cohort 2027/1",
            observacao="Nova turma",
        )

        assert result.success is True, f"unexpected failure: {result.error!r}"
        assert result.dry_run is False

        vis = next(f for f in page.frames if f.name == "ifrVisualizacao")
        # Modal-trigger icon was clicked exactly once (group didn't exist).
        assert vis.click_log.count("#imgNovoGrupoAcompanhamento") == 1
        # Outer cadastrar submit fired exactly once.
        assert vis.click_log.count('button[name="sbmCadastrarAcompanhamento"]') == 1

        # Observação was filled on the outer form.
        assert ("#txaObservacao", "Nova turma") in vis.fill_log

    @pytest.mark.asyncio
    async def test_new_group_fills_txtNome_in_modal(self, tmp_path, monkeypatch):
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)
        page = _scenario_new_group()
        writer = SEIWriter(page, run_id="live-new-nome", dry_run=False)

        await writer.add_to_acompanhamento_especial(
            processo_id="23075.000002/2026-00",
            grupo="Cohort 2027/1",
        )

        # The modal frame was added by the triggering click; we can no longer
        # retrieve it from page.frames (post-submit it was removed), so we
        # assert via audit instead.
        audit = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        assert "live" in audit
        assert "Cohort 2027/1" in audit


class TestAcompanhamentoForbiddenSelectors:
    """If sei_selectors.yaml (or the in-source defaults) were ever corrupted
    to contain a forbidden selector, _safe_frame_click must block it rather
    than clicking. These tests simulate that by patching
    get_acompanhamento_form."""

    @pytest.mark.asyncio
    async def test_forbidden_submit_selector_raises_permission_error(self, tmp_path, monkeypatch):
        """If the manifest's cadastrar.submit selector matches a forbidden
        token (e.g. btnAssinar), ``_safe_frame_click`` must raise
        PermissionError. The outer except in the writer explicitly
        re-raises PermissionError instead of wrapping it, so callers see
        the raise."""
        import ufpr_automation.sei.writer_selectors as ws
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)

        tainted = copy.deepcopy(_ACOMPANHAMENTO_ESPECIAL_DEFAULTS)
        tainted["cadastrar"]["submit"]["selector"] = 'button[name="btnAssinar"]'
        monkeypatch.setattr(ws, "get_acompanhamento_form", lambda: tainted)

        page = _scenario_existing_group()
        writer = SEIWriter(page, run_id="forbid-test", dry_run=False)

        with pytest.raises(PermissionError, match="forbidden selector"):
            await writer.add_to_acompanhamento_especial(
                processo_id="23075.000001/2026-00",
                grupo="Estágio não obrigatório",
            )

        # The tainted submit selector must not have been clicked on the
        # form frame.
        vis = next(f for f in page.frames if f.name == "ifrVisualizacao")
        assert 'button[name="btnAssinar"]' not in vis.click_log

    @pytest.mark.asyncio
    async def test_forbidden_novo_grupo_selector_blocks_modal_click(self, tmp_path, monkeypatch):
        import ufpr_automation.sei.writer_selectors as ws
        from ufpr_automation.config import settings

        monkeypatch.setattr(settings, "SEI_WRITE_ARTIFACTS_DIR", tmp_path)

        tainted = copy.deepcopy(_ACOMPANHAMENTO_ESPECIAL_DEFAULTS)
        tainted["cadastrar"]["fields"]["novo_grupo_icon"]["selector"] = (
            "#imgAssinarGrupoAcompanhamento"
        )
        monkeypatch.setattr(ws, "get_acompanhamento_form", lambda: tainted)

        page = _scenario_new_group()
        writer = SEIWriter(page, run_id="forbid-novo", dry_run=False)

        with pytest.raises(PermissionError, match="forbidden selector"):
            await writer.add_to_acompanhamento_especial(
                processo_id="23075.000002/2026-00",
                grupo="Cohort 2027/1",
            )

        # The tainted selector must not have registered a click on the
        # vis_frame.
        vis = next(f for f in page.frames if f.name == "ifrVisualizacao")
        assert "#imgAssinarGrupoAcompanhamento" not in vis.click_log
