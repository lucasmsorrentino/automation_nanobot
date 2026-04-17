"""Safety regression tests for ufpr_automation.outlook.responder.

CRITICAL INVARIANT
==================
``save_draft_reply`` must NEVER click or otherwise activate a Send / Enviar /
Submit affordance. Every pipeline action must remain in the draft state,
requiring explicit human approval before the email leaves the organisation.

If this test file ever fails, STOP and audit the change: it means a code path
has been introduced that could auto-send an email to a real UFPR student.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ufpr_automation.outlook import responder

# Words that, if clicked, would cause the draft to actually be SENT.
FORBIDDEN_CLICK_TEXTS = [
    "enviar",
    "send",
    "submit",
]


def _assert_no_forbidden_clicks(forbidden_calls: list[str]) -> None:
    """Shared assertion helper for every save_draft_reply test path."""
    for entry in forbidden_calls:
        lowered = entry.lower()
        for forbidden in FORBIDDEN_CLICK_TEXTS:
            assert forbidden not in lowered, (
                f"SAFETY VIOLATION: save_draft_reply attempted to click/query "
                f"'{entry}' which matches forbidden word '{forbidden}'. "
                f"Drafts must never be auto-sent — only saved."
            )


class _RecordingPage:
    """A minimal Playwright-Page stand-in that records every selector /
    keyboard interaction ``save_draft_reply`` performs.

    All query_selector / wait_for_selector / keyboard calls pump into
    ``self.inspected`` so the regression test can inspect the full interaction
    trace and fail loudly if anything Send-like slips in.
    """

    def __init__(self) -> None:
        self.inspected: list[str] = []  # selectors/keys the code touched
        self.clicked: list[str] = []  # text that was actually click()ed
        self.keyboard = MagicMock()
        self.keyboard.press = AsyncMock(side_effect=self._record_key)
        self.keyboard.type = AsyncMock(return_value=None)

    async def _record_key(self, key: str) -> None:
        self.inspected.append(f"keyboard:{key}")

    async def query_selector(self, selector: str):
        self.inspected.append(f"query_selector:{selector}")
        # Simulate a Reply button being present for the first Reply selector,
        # and then the compose area existing afterwards. Every other call
        # returns None so the code path stays minimal.
        if "Reply" in selector or "Responder" in selector:
            return self._make_reply_element(selector)
        if (
            "contenteditable" in selector
            or "Message body" in selector
            or "Corpo da mensagem" in selector
            or "textbox" in selector
        ):
            return self._make_compose_element(selector)
        return None

    async def query_selector_all(self, selector: str):
        self.inspected.append(f"query_selector_all:{selector}")
        return []

    async def wait_for_selector(self, selector: str, *args, **kwargs):
        self.inspected.append(f"wait_for_selector:{selector}")
        return object()  # pretend it always resolves

    async def wait_for_load_state(self, *_args, **_kwargs):
        return None

    async def wait_for_timeout(self, *_args, **_kwargs):
        return None

    def _make_reply_element(self, selector: str):
        parent = self

        class _Element:
            async def click(self):
                parent.clicked.append(f"click:{selector}")

            async def is_visible(self):
                return True

            async def type(self, *_args, **_kwargs):
                return None

        return _Element()

    def _make_compose_element(self, selector: str):
        parent = self

        class _ComposeEl:
            async def click(self):
                parent.clicked.append(f"click:{selector}")

            async def is_visible(self):
                return True

            async def type(self, text: str, *args, **kwargs):
                parent.inspected.append(f"compose_type:{text[:40]}")

        return _ComposeEl()


class TestSaveDraftReplySafety:
    @pytest.mark.asyncio
    async def test_save_draft_never_clicks_send_or_submit(self):
        """Regression test: save_draft_reply must never touch Send/Enviar/Submit."""
        page = _RecordingPage()

        ok = await responder.save_draft_reply(
            page,  # type: ignore[arg-type]
            "Prezado(a), agradecemos o contato. Atenciosamente, Coordenacao.",
        )

        assert ok is True

        # Nothing in inspected / clicked should contain send / enviar / submit.
        _assert_no_forbidden_clicks(page.inspected)
        _assert_no_forbidden_clicks(page.clicked)

        # Sanity: the draft was saved via Ctrl+S, not by clicking a Send button.
        assert any("keyboard:Control+s" in entry for entry in page.inspected)

    @pytest.mark.asyncio
    async def test_selector_banks_contain_no_send_patterns(self):
        """Every selector bank in responder.py should be free of Send strings."""
        all_selectors = (
            responder._REPLY_BUTTON_SELECTORS
            + responder._COMPOSE_AREA_SELECTORS
            + responder._CLOSE_COMPOSE_SELECTORS
        )
        for sel in all_selectors:
            lowered = sel.lower()
            for forbidden in FORBIDDEN_CLICK_TEXTS:
                assert forbidden not in lowered, (
                    f"SAFETY VIOLATION: selector bank contains '{sel}' which "
                    f"matches forbidden word '{forbidden}'."
                )

    @pytest.mark.asyncio
    async def test_reply_button_not_found_returns_false(self):
        """If no Reply button is found we should bail out, not send."""
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.wait_for_selector = AsyncMock(side_effect=Exception("not found"))
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock()

        ok = await responder.save_draft_reply(page, "Teste de resposta.")  # type: ignore[arg-type]
        assert ok is False
        # Nothing should have been typed into a compose area.
        page.keyboard.press.assert_not_called()

    @pytest.mark.asyncio
    async def test_dismiss_owa_dialog_no_dialog_is_noop(self):
        """If no dialog is present, dismiss_owa_dialog should not crash nor click anything send-like."""
        page = AsyncMock()
        page.query_selector = AsyncMock(return_value=None)
        page.keyboard = MagicMock()
        page.keyboard.press = AsyncMock()

        # Should return without raising.
        await responder.dismiss_owa_dialog(page)  # type: ignore[arg-type]
        # No keypress (Escape) should be attempted when no dialog is visible.
        page.keyboard.press.assert_not_called()
