"""Tests for graph/nodes.py — LangGraph pipeline node functions."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from ufpr_automation.core.models import EmailClassification, EmailData
from ufpr_automation.graph.nodes import (
    CONFIDENCE_HIGH,
    rotear,
)


@pytest.fixture
def sample_emails():
    emails = []
    for i, (sender, subject) in enumerate(
        [
            ("prof@ufpr.br", "Solicitação de Estágio"),
            ("sec@ufpr.br", "Informe Reunião"),
            ("spam@fake.com", "Promoção imperdível"),
        ]
    ):
        e = EmailData(sender=sender, subject=subject, body=f"Corpo do email {i}")
        e.compute_stable_id()
        emails.append(e)
    return emails


@pytest.fixture
def sample_classifications(sample_emails):
    return {
        sample_emails[0].stable_id: EmailClassification(
            categoria="Estágios",
            resumo="Solicitação de estágio",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Prezado...",
            confianca=0.98,  # HIGH → auto-draft
        ),
        sample_emails[1].stable_id: EmailClassification(
            categoria="Outros",
            resumo="Aviso de reunião",
            acao_necessaria="Arquivar",
            sugestao_resposta="Obrigado pelo aviso.",
            confianca=0.80,  # MEDIUM → human review
        ),
        sample_emails[2].stable_id: EmailClassification(
            categoria="Correio Lixo",
            resumo="Spam detectado",
            acao_necessaria="Ignorar",
            sugestao_resposta="",
            confianca=0.55,  # LOW → manual escalation
        ),
    }


class TestRotear:
    """Test confidence-based routing logic."""

    def test_high_confidence_auto_draft(self, sample_emails, sample_classifications):
        state = {"classifications": sample_classifications}
        result = rotear(state)

        assert sample_emails[0].stable_id in result["auto_draft"]
        assert sample_emails[0].stable_id not in result["human_review"]
        assert sample_emails[0].stable_id not in result["manual_escalation"]

    def test_medium_confidence_human_review(self, sample_emails, sample_classifications):
        state = {"classifications": sample_classifications}
        result = rotear(state)

        assert sample_emails[1].stable_id in result["human_review"]
        assert sample_emails[1].stable_id not in result["auto_draft"]

    def test_low_confidence_manual_escalation(self, sample_emails, sample_classifications):
        state = {"classifications": sample_classifications}
        result = rotear(state)

        assert sample_emails[2].stable_id in result["manual_escalation"]
        assert sample_emails[2].stable_id not in result["auto_draft"]
        assert sample_emails[2].stable_id not in result["human_review"]

    def test_empty_classifications(self):
        state = {"classifications": {}}
        result = rotear(state)
        assert result["auto_draft"] == []
        assert result["human_review"] == []
        assert result["manual_escalation"] == []

    def test_threshold_boundary_high(self, sample_emails):
        """Exactly at CONFIDENCE_HIGH boundary should be auto_draft."""
        cls = EmailClassification(
            categoria="Estágios",
            resumo="test",
            acao_necessaria="test",
            sugestao_resposta="test",
            confianca=CONFIDENCE_HIGH,
        )
        state = {"classifications": {sample_emails[0].stable_id: cls}}
        result = rotear(state)
        assert sample_emails[0].stable_id in result["auto_draft"]

    def test_threshold_boundary_medium(self, sample_emails):
        """Just below CONFIDENCE_HIGH should be human_review."""
        cls = EmailClassification(
            categoria="Estágios",
            resumo="test",
            acao_necessaria="test",
            sugestao_resposta="test",
            confianca=CONFIDENCE_HIGH - 0.01,
        )
        state = {"classifications": {sample_emails[0].stable_id: cls}}
        result = rotear(state)
        assert sample_emails[0].stable_id in result["human_review"]


class TestSaveRunResults:
    """Test that pipeline results are saved for feedback review."""

    def test_saves_jsonl(self, sample_emails, sample_classifications, tmp_path):
        from ufpr_automation.graph.nodes import _save_run_results

        with patch("ufpr_automation.feedback.store.FEEDBACK_DIR", tmp_path):
            _save_run_results(sample_emails, sample_classifications)

        results_file = tmp_path / "last_run.jsonl"
        assert results_file.exists()

        lines = results_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3

        first = json.loads(lines[0])
        assert "email_hash" in first
        assert "sender" in first
        assert "subject" in first
        assert "classification" in first
        assert first["classification"]["categoria"] in [
            "Estágios",
            "Outros",
            "Correio Lixo",
        ]


# ---------------------------------------------------------------------------
# prewarm_sessions — gated SEI/SIGA session warming before Fleet fan-out
# ---------------------------------------------------------------------------


class TestPrewarmSessions:
    def _mk_email(self, subject: str, body: str = ""):
        e = EmailData(sender="x@y.z", subject=subject, body=body)
        e.compute_stable_id()
        return e

    def test_disabled_by_default(self, monkeypatch):
        """Without PREWARM_SESSIONS_ENABLED set, the node is a no-op."""
        from ufpr_automation.graph.nodes import prewarm_sessions

        monkeypatch.delenv("PREWARM_SESSIONS_ENABLED", raising=False)
        called = []
        monkeypatch.setattr(
            "ufpr_automation.graph.nodes._prewarm_sessions_async",
            lambda *a, **kw: called.append(1) or None,
        )
        out = prewarm_sessions(
            {"emails": [self._mk_email("SEI 23075.123456/2026-01")]}
        )
        assert out == {}
        assert called == []  # async path must not run

    def test_skips_when_no_sei_grr_mentioned(self, monkeypatch):
        """Enabled + emails without SEI/GRR patterns → skip (no login)."""
        from ufpr_automation.graph.nodes import prewarm_sessions

        monkeypatch.setenv("PREWARM_SESSIONS_ENABLED", "true")
        called = []
        monkeypatch.setattr(
            "ufpr_automation.graph.nodes._prewarm_sessions_async",
            lambda *a, **kw: called.append(1) or None,
        )
        out = prewarm_sessions(
            {"emails": [self._mk_email("Promoção imperdível", "desconto exclusivo")]}
        )
        assert out == {}
        assert called == []

    def test_runs_async_when_enabled_and_sei_mentioned(self, monkeypatch):
        """Enabled + SEI number in email → async warming executes."""
        import asyncio

        from ufpr_automation.graph.nodes import prewarm_sessions

        monkeypatch.setenv("PREWARM_SESSIONS_ENABLED", "1")
        executed = {}

        async def _fake_warm(max_age_h):
            executed["max_age_h"] = max_age_h

        monkeypatch.setattr(
            "ufpr_automation.graph.nodes._prewarm_sessions_async", _fake_warm
        )
        # Use asyncio.run passthrough — the node's own asyncio.run will drive it.
        out = prewarm_sessions(
            {"emails": [self._mk_email("Encaminho TCE", "processo 23075.123456/2026-01")]}
        )
        assert out == {}
        assert executed == {"max_age_h": 6.0}

    def test_max_age_env_var_respected(self, monkeypatch):
        """PREWARM_SESSIONS_MAX_AGE_H overrides the default 6h window."""
        from ufpr_automation.graph.nodes import prewarm_sessions

        monkeypatch.setenv("PREWARM_SESSIONS_ENABLED", "true")
        monkeypatch.setenv("PREWARM_SESSIONS_MAX_AGE_H", "12")
        executed = {}

        async def _fake_warm(max_age_h):
            executed["max_age_h"] = max_age_h

        monkeypatch.setattr(
            "ufpr_automation.graph.nodes._prewarm_sessions_async", _fake_warm
        )
        prewarm_sessions({"emails": [self._mk_email("GRR20231234", "")]})
        assert executed["max_age_h"] == 12.0

    def test_async_errors_are_swallowed(self, monkeypatch, caplog):
        """An exception inside the async path must not fail the pipeline."""
        from ufpr_automation.graph.nodes import prewarm_sessions

        monkeypatch.setenv("PREWARM_SESSIONS_ENABLED", "true")

        async def _bad(max_age_h):
            raise RuntimeError("boom")

        monkeypatch.setattr(
            "ufpr_automation.graph.nodes._prewarm_sessions_async", _bad
        )
        # Must not raise.
        out = prewarm_sessions(
            {"emails": [self._mk_email("SEI 23075.123456/2026-01")]}
        )
        assert out == {}

    def test_fresh_session_file_short_circuits(self, monkeypatch, tmp_path):
        """_prewarm_sessions_async must skip systems whose session file is young."""
        import asyncio
        import time

        # Point the session files at tmp_path and touch them fresh.
        sei_file = tmp_path / "sei_state.json"
        siga_file = tmp_path / "siga_state.json"
        sei_file.write_text("{}")
        siga_file.write_text("{}")
        # Both files freshly created → age ~0h → skip both.

        from ufpr_automation.sei import browser as sei_browser
        from ufpr_automation.siga import browser as siga_browser

        monkeypatch.setattr(sei_browser, "SEI_SESSION_FILE", sei_file)
        monkeypatch.setattr(siga_browser, "SIGA_SESSION_FILE", siga_file)

        login_calls = []

        async def _fake_login(page):
            login_calls.append(page)
            return True

        monkeypatch.setattr(sei_browser, "auto_login", _fake_login)
        monkeypatch.setattr(siga_browser, "auto_login", _fake_login)

        from ufpr_automation.graph.nodes import _prewarm_sessions_async

        asyncio.run(_prewarm_sessions_async(max_age_h=6.0))
        # Neither system should have logged in — files are fresh.
        assert login_calls == []

    def test_stale_session_file_triggers_login(self, monkeypatch, tmp_path):
        """_prewarm_sessions_async must re-login when session file is older than max_age_h."""
        import asyncio
        import os as _os
        import time

        sei_file = tmp_path / "sei_state.json"
        sei_file.write_text("{}")
        # Backdate the SEI file 10 hours into the past.
        old = time.time() - 10 * 3600
        _os.utime(sei_file, (old, old))

        # Leave SIGA file fresh so it skips (isolates SEI path).
        siga_file = tmp_path / "siga_state.json"
        siga_file.write_text("{}")

        from ufpr_automation.sei import browser as sei_browser
        from ufpr_automation.siga import browser as siga_browser

        monkeypatch.setattr(sei_browser, "SEI_SESSION_FILE", sei_file)
        monkeypatch.setattr(siga_browser, "SIGA_SESSION_FILE", siga_file)

        logged_in_systems = []

        # Stub out the whole browser chain so no real Playwright spawns.
        class _FakePage:
            async def goto(self, *a, **kw):
                pass

        class _FakeCtx:
            async def new_page(self):
                return _FakePage()

        class _FakeBrowser:
            async def close(self):
                pass

        class _FakePW:
            async def stop(self):
                pass

        async def _launch(headless=True):
            return _FakePW(), _FakeBrowser()

        async def _ctx(browser, headless=True):
            return _FakeCtx()

        async def _save(ctx):
            pass

        async def _login_sei(page):
            logged_in_systems.append("SEI")
            return True

        async def _login_siga(page):
            logged_in_systems.append("SIGA")
            return True

        for mod, login in [(sei_browser, _login_sei), (siga_browser, _login_siga)]:
            monkeypatch.setattr(mod, "launch_browser", _launch)
            monkeypatch.setattr(mod, "create_browser_context", _ctx)
            monkeypatch.setattr(mod, "save_session_state", _save)
            monkeypatch.setattr(mod, "auto_login", login)
            monkeypatch.setattr(mod, "has_credentials", lambda: True)

        from ufpr_automation.graph.nodes import _prewarm_sessions_async

        asyncio.run(_prewarm_sessions_async(max_age_h=6.0))
        # Only SEI was stale — SIGA fresh file must have been skipped.
        assert logged_in_systems == ["SEI"]

    def test_missing_credentials_skips_login(self, monkeypatch, tmp_path):
        """If credentials are missing, skip the login for that system."""
        import asyncio

        sei_file = tmp_path / "sei_state.json"  # absent by design
        siga_file = tmp_path / "siga_state.json"

        from ufpr_automation.sei import browser as sei_browser
        from ufpr_automation.siga import browser as siga_browser

        monkeypatch.setattr(sei_browser, "SEI_SESSION_FILE", sei_file)
        monkeypatch.setattr(siga_browser, "SIGA_SESSION_FILE", siga_file)
        monkeypatch.setattr(sei_browser, "has_credentials", lambda: False)
        monkeypatch.setattr(siga_browser, "has_credentials", lambda: False)

        login_calls = []

        async def _fake_login(page):
            login_calls.append(page)
            return True

        monkeypatch.setattr(sei_browser, "auto_login", _fake_login)
        monkeypatch.setattr(siga_browser, "auto_login", _fake_login)

        from ufpr_automation.graph.nodes import _prewarm_sessions_async

        asyncio.run(_prewarm_sessions_async(max_age_h=6.0))
        assert login_calls == []


# ---------------------------------------------------------------------------
# agir_gmail skip path + capturar_corpus_humano
# ---------------------------------------------------------------------------


class TestAgirGmailSkipAlreadyReplied:
    """When EmailData.already_replied_by_us is True, agir_gmail must NOT
    save a draft — the human coordinator already handled this thread.
    """

    def test_skips_draft_when_already_replied(self, monkeypatch):
        from ufpr_automation.graph.nodes import agir_gmail

        email = EmailData(
            sender="aluno@ufpr.br",
            subject="Solicitação de TCE",
            body="...",
            gmail_msg_id="42",
            gmail_message_id="<student-1@example.com>",
            already_replied_by_us=True,
        )
        email.compute_stable_id()
        cls = EmailClassification(
            categoria="Estágios",
            resumo="...",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Texto que NÃO deve ser enviado.",
            confianca=0.99,
        )

        saved_drafts: list = []

        class _FakeGmail:
            def save_draft(self, **kw):
                saved_drafts.append(kw)
                return True

            def mark_read(self, *_a, **_kw):
                pass

            def apply_labels(self, *_a, **_kw):
                return True

        monkeypatch.setattr(
            "ufpr_automation.gmail.client.GmailClient", lambda *_a, **_kw: _FakeGmail()
        )

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "auto_draft": [email.stable_id],
            "human_review": [],
        }
        result = agir_gmail(state)
        assert saved_drafts == []
        assert result["drafts_saved"] == []
        assert result["drafts_skipped_already_replied"] == [email.stable_id]

    def test_normal_path_still_drafts(self, monkeypatch):
        from ufpr_automation.graph.nodes import agir_gmail

        email = EmailData(
            sender="aluno@ufpr.br",
            subject="Solicitação de TCE",
            body="...",
            gmail_msg_id="43",
            gmail_message_id="<student-2@example.com>",
            already_replied_by_us=False,
        )
        email.compute_stable_id()
        cls = EmailClassification(
            categoria="Estágios",
            resumo="...",
            acao_necessaria="Redigir Resposta",
            sugestao_resposta="Texto a enviar.",
            confianca=0.99,
        )

        saved: list = []

        class _FakeGmail:
            def save_draft(self, **kw):
                saved.append(kw)
                return True

            def mark_read(self, *_a, **_kw):
                pass

            def apply_labels(self, *_a, **_kw):
                return True

        monkeypatch.setattr(
            "ufpr_automation.gmail.client.GmailClient", lambda *_a, **_kw: _FakeGmail()
        )

        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "auto_draft": [email.stable_id],
            "human_review": [],
        }
        result = agir_gmail(state)
        assert len(saved) == 1
        assert result["drafts_saved"] == [email.stable_id]
        assert result["drafts_skipped_already_replied"] == []


class TestCapturarCorpusHumano:
    """Corpus capture should:
    - No-op when no emails are flagged.
    - Copy the thread to the label + append a JSONL entry when flagged.
    - Be idempotent across runs (second run on the same thread doesn't re-append).
    - Mark the CC'd reply as read after capture.
    """

    def test_no_flagged_emails_is_noop(self, tmp_path, monkeypatch):
        from ufpr_automation.graph.nodes import capturar_corpus_humano

        monkeypatch.setattr("ufpr_automation.feedback.store.FEEDBACK_DIR", tmp_path)
        email = EmailData(sender="aluno@ufpr.br", subject="x", body="", already_replied_by_us=False)
        email.compute_stable_id()
        result = capturar_corpus_humano({"emails": [email], "classifications": {}})
        assert result == {"corpus_captured": []}

    def test_missing_label_is_noop(self, tmp_path, monkeypatch):
        from ufpr_automation.graph import nodes
        from ufpr_automation.graph.nodes import capturar_corpus_humano

        monkeypatch.setattr("ufpr_automation.feedback.store.FEEDBACK_DIR", tmp_path)
        # Disable the label via settings.
        from ufpr_automation.config import settings as _settings
        monkeypatch.setattr(_settings, "GMAIL_LEARNING_LABEL", "")

        email = EmailData(
            sender="aluno@ufpr.br",
            subject="x",
            body="",
            gmail_message_id="<m@x>",
            already_replied_by_us=True,
        )
        email.compute_stable_id()
        result = capturar_corpus_humano({"emails": [email], "classifications": {}})
        assert result == {"corpus_captured": []}

    def test_captures_flagged_thread_and_writes_jsonl(self, tmp_path, monkeypatch):
        from ufpr_automation.graph.nodes import capturar_corpus_humano

        monkeypatch.setattr("ufpr_automation.feedback.store.FEEDBACK_DIR", tmp_path)

        copy_calls: list[tuple[str, str]] = []
        marked_read: list[str] = []

        class _FakeGmail:
            def copy_thread_to_label(self, mid, label):
                copy_calls.append((mid, label))
                return (3, "777")

            def mark_read(self, msn):
                marked_read.append(msn)

        monkeypatch.setattr(
            "ufpr_automation.gmail.client.GmailClient", lambda *_a, **_kw: _FakeGmail()
        )

        email = EmailData(
            sender="Secretaria <design.grafico@ufpr.br>",
            subject="Re: TCE João",
            body="...",
            gmail_msg_id="99",
            gmail_message_id="<coord-1@example.com>",
            already_replied_by_us=True,
        )
        email.compute_stable_id()
        cls = EmailClassification(
            categoria="Estágios",
            resumo="r",
            acao_necessaria="a",
            sugestao_resposta="",
            confianca=0.9,
        )

        result = capturar_corpus_humano({
            "emails": [email],
            "classifications": {email.stable_id: cls},
        })
        assert len(copy_calls) == 1
        assert copy_calls[0][0] == "<coord-1@example.com>"
        assert marked_read == ["99"]
        assert len(result["corpus_captured"]) == 1

        # JSONL must have one entry with the captured metadata.
        jsonl = tmp_path / "learning_corpus.jsonl"
        assert jsonl.exists()
        lines = [json.loads(ln) for ln in jsonl.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 1
        entry = lines[0]
        assert entry["thread_id"] == "777"
        assert entry["stable_id"] == email.stable_id
        assert entry["categoria"] == "Estágios"
        assert entry["label"]  # default from settings
        assert email.thread_id == "777"

    def test_idempotent_across_runs(self, tmp_path, monkeypatch):
        from ufpr_automation.graph.nodes import capturar_corpus_humano

        monkeypatch.setattr("ufpr_automation.feedback.store.FEEDBACK_DIR", tmp_path)

        class _FakeGmail:
            def copy_thread_to_label(self, mid, label):
                return (2, "888")

            def mark_read(self, msn):
                pass

        monkeypatch.setattr(
            "ufpr_automation.gmail.client.GmailClient", lambda *_a, **_kw: _FakeGmail()
        )

        email = EmailData(
            sender="design.grafico@ufpr.br",
            subject="Re: x",
            body="",
            gmail_msg_id="11",
            gmail_message_id="<m@x>",
            already_replied_by_us=True,
        )
        email.compute_stable_id()
        state = {"emails": [email], "classifications": {}}

        r1 = capturar_corpus_humano(state)
        r2 = capturar_corpus_humano(state)
        assert len(r1["corpus_captured"]) == 1
        # Second run finds the thread already in JSONL — no new append.
        assert r2["corpus_captured"] == []
        jsonl = tmp_path / "learning_corpus.jsonl"
        lines = [ln for ln in jsonl.read_text(encoding="utf-8").splitlines() if ln]
        assert len(lines) == 1


class TestAgirEstagiosSkipAlreadyReplied:
    """agir_estagios must bail out on emails already handled by the human."""

    def test_skips_estagios_sei_flow_when_already_replied(self, monkeypatch):
        from ufpr_automation.core.models import EmailClassification, EmailData
        from ufpr_automation.graph.nodes import agir_estagios

        email = EmailData(
            sender="aluno@ufpr.br",
            subject="TCE nº 12345",
            body="Termo de Compromisso ...",
            gmail_message_id="<s@x>",
            already_replied_by_us=True,
        )
        email.compute_stable_id()
        cls = EmailClassification(
            categoria="Estágios",
            resumo="r",
            acao_necessaria="a",
            sugestao_resposta="placeholder",
            confianca=0.9,
        )
        state = {
            "emails": [email],
            "classifications": {email.stable_id: cls},
            "tier0_hits": [email.stable_id],
            "sei_contexts": {},
            "siga_contexts": {},
        }
        # If agir_estagios DID run the SEI flow, it'd try to import/instantiate
        # the playbook/checkers — patching not strictly needed since we expect
        # an early skip. Assert sei_operations stays empty.
        result = agir_estagios(state)
        assert result.get("sei_operations", []) == []


class TestRunAsyncSafe:
    """Regression for the baseline-topology RuntimeError bug.

    Sync LangGraph nodes (consultar_sei/siga, agir_estagios) call into async
    helpers. When the pipeline is driven from an already-running event loop
    (CLI does ``asyncio.run(run_gmail_channel())`` → ``graph.invoke()``),
    plain ``asyncio.run`` raises. ``_run_async_safe`` must work in both
    contexts.
    """

    def test_runs_coroutine_without_existing_loop(self):
        """No running loop in the current thread → direct asyncio.run path."""
        from ufpr_automation.graph.nodes import _run_async_safe

        async def _work():
            return 42

        assert _run_async_safe(_work()) == 42

    def test_runs_coroutine_inside_running_loop(self):
        """A coroutine inside a running loop offloads to a worker thread.

        This simulates exactly what LangGraph does when a sync node calls a
        helper that uses ``asyncio.run`` internally. Without the helper it
        would raise ``RuntimeError: asyncio.run() cannot be called from a
        running event loop``.
        """
        import asyncio

        from ufpr_automation.graph.nodes import _run_async_safe

        async def _inner():
            return "ok"

        async def _outer():
            # Inside a running loop here — simulate the LangGraph setup
            return _run_async_safe(_inner())

        assert asyncio.run(_outer()) == "ok"

    def test_propagates_exception_from_worker_thread(self):
        """An exception raised in the worker thread must propagate."""
        import asyncio

        from ufpr_automation.graph.nodes import _run_async_safe

        async def _boom():
            raise ValueError("boom")

        async def _outer():
            return _run_async_safe(_boom())

        import pytest

        with pytest.raises(ValueError, match="boom"):
            asyncio.run(_outer())


# ----------------------------------------------------------------------
# SIGA coverage gap fix (2026-04-30 part 3) — _consult_siga_async agora
# expoe matricula_status / curriculo_integralizado / nao_vencidas /
# reprovacoes_total derivados de EligibilityResult, ate aqui descartados.
# ----------------------------------------------------------------------


class TestNormalizeMatriculaStatus:
    @pytest.mark.parametrize(
        "siga_text",
        [
            "Ativa",
            "Ativo",
            "Registro ativo",
            "MATRICULA ATIVA",
            "ativa",  # lowercase
        ],
    )
    def test_active_variants_map_to_ATIVA(self, siga_text):
        from ufpr_automation.graph.nodes import _normalize_matricula_status

        assert _normalize_matricula_status(siga_text) == "ATIVA"

    @pytest.mark.parametrize(
        "siga_text,expected",
        [
            ("Trancada", "TRANCADA"),
            ("Cancelada", "CANCELADA"),
            ("Abandonada", "ABANDONADA"),
            ("Integralizada", "INTEGRALIZADA"),
        ],
    )
    def test_blocking_variants_pass_through_uppercased(self, siga_text, expected):
        from ufpr_automation.graph.nodes import _normalize_matricula_status

        assert _normalize_matricula_status(siga_text) == expected

    def test_empty_string_returns_empty(self):
        from ufpr_automation.graph.nodes import _normalize_matricula_status

        assert _normalize_matricula_status("") == ""

    def test_none_returns_empty(self):
        from ufpr_automation.graph.nodes import _normalize_matricula_status

        # mypy-style: caller may pass None despite the type hint.
        assert _normalize_matricula_status(None) == ""  # type: ignore[arg-type]


class TestEligibilityToSigaContext:
    """Funcao pura que mapeia EligibilityResult -> dict pra siga_contexts."""

    def _make_eligibility(self, **overrides):
        from ufpr_automation.siga.models import EligibilityResult, StudentStatus

        student = overrides.pop(
            "student",
            StudentStatus(
                grr="GRR20244602",
                nome="LETICIA FONCECA RAMALHO",
                curso="Design Grafico",
                situacao="Registro ativo",
            ),
        )
        return EligibilityResult(
            eligible=overrides.pop("eligible", True),
            reasons=overrides.pop("reasons", []),
            warnings=overrides.pop("warnings", []),
            student=student,
            historico_data=overrides.pop("historico_data", {}),
            integralizacao_data=overrides.pop("integralizacao_data", {}),
        )

    def test_basic_keys_always_present(self):
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context("GRR20244602", self._make_eligibility())

        assert ctx["grr"] == "GRR20244602"
        assert ctx["eligible"] is True
        assert ctx["reasons"] == []
        assert ctx["warnings"] == []
        # student-derived keys
        assert ctx["nome"] == "LETICIA FONCECA RAMALHO"
        assert ctx["situacao"] == "Registro ativo"
        assert ctx["curso"] == "Design Grafico"
        assert ctx["matricula_status"] == "ATIVA"

    def test_no_student_omits_student_keys(self):
        """Student None (aluno nao encontrado) — nao popular nome/situacao etc."""
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context(
            "GRR20244602", self._make_eligibility(student=None, eligible=False)
        )

        for key in ("nome", "situacao", "curso", "matricula_status"):
            assert key not in ctx

    def test_empty_situacao_omits_matricula_status_for_failsafe(self):
        """Quando ``_extract_info_gerais`` nao achou o campo Status na
        pagina (situacao=""), nao popular ``matricula_status`` — checker
        cai em soft_block "SIGA nao consultado" em vez de hard-block
        falso. Bug visto no smoke da Leticia 2026-04-30."""
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context
        from ufpr_automation.siga.models import StudentStatus

        student = StudentStatus(grr="GRR20244602", nome="LETICIA", situacao="")
        ctx = _eligibility_to_siga_context(
            "GRR20244602", self._make_eligibility(student=student)
        )

        assert "matricula_status" not in ctx
        assert ctx["situacao"] == ""  # raw situacao ainda preservado pra log
        assert ctx["nome"] == "LETICIA"

    def test_curriculo_integralizado_exposed_from_integ_data(self):
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context(
            "GRR20244602",
            self._make_eligibility(integralizacao_data={"integralizado": True}),
        )

        assert ctx["curriculo_integralizado"] is True

    def test_curriculo_integralizado_false_exposed(self):
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context(
            "GRR20244602",
            self._make_eligibility(integralizacao_data={"integralizado": False}),
        )

        assert ctx["curriculo_integralizado"] is False

    def test_nao_vencidas_exposed_for_jornada_checker(self):
        """``tce_jornada_antes_meio_dia`` precisa da lista pra aplicar a
        excecao TCC/Estagio Supervisionado (2026-04-30)."""
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context(
            "GRR20244602",
            self._make_eligibility(
                integralizacao_data={
                    "integralizado": False,
                    "nao_vencidas": ["OD501", "ODDA6"],
                }
            ),
        )

        assert ctx["nao_vencidas"] == ["OD501", "ODDA6"]

    def test_reprovacoes_total_exposed(self):
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context(
            "GRR20244602",
            self._make_eligibility(historico_data={"reprovacoes_total": 5}),
        )

        assert ctx["reprovacoes_total"] == 5

    def test_missing_integ_and_historico_omits_optional_keys(self):
        """Sem dados de integralizacao/historico — nao popular as chaves
        derivadas (faz checkers caırem em soft_block fail-safe)."""
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context("GRR20244602", self._make_eligibility())

        for key in (
            "curriculo_integralizado",
            "nao_vencidas",
            "reprovacoes_total",
        ):
            assert key not in ctx

    def test_reasons_and_warnings_are_copied_not_aliased(self):
        """Mutar o dict resultante nao deve mutar o EligibilityResult."""
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        elig = self._make_eligibility(
            reasons=["aluno trancado"], warnings=["alerta"]
        )
        ctx = _eligibility_to_siga_context("GRR20244602", elig)
        ctx["reasons"].append("MUTATION")
        ctx["warnings"].append("MUTATION")

        assert "MUTATION" not in elig.reasons
        assert "MUTATION" not in elig.warnings

    def test_full_letícia_payload_satisfies_jornada_exception(self):
        """Smoke 2026-04-30: aluna real com pendentes ⊆ {OD501, ODDA6, ODDA7}.
        O dict resultante precisa ter ``nao_vencidas`` populado pro
        checker ``tce_jornada_antes_meio_dia`` aplicar a excecao."""
        from ufpr_automation.graph.nodes import _eligibility_to_siga_context

        ctx = _eligibility_to_siga_context(
            "GRR20244602",
            self._make_eligibility(
                integralizacao_data={
                    "integralizado": False,
                    "nao_vencidas": ["OD501", "ODDA6", "ODDA7"],
                },
                historico_data={"reprovacoes_total": 0},
            ),
        )

        # Sao as chaves que os checkers olham.
        assert ctx["matricula_status"] == "ATIVA"
        assert ctx["curriculo_integralizado"] is False
        assert set(ctx["nao_vencidas"]) == {"OD501", "ODDA6", "ODDA7"}
        assert ctx["reprovacoes_total"] == 0
