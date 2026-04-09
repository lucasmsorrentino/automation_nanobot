"""Split an email body into the new reply and the quoted history.

Most email clients (Gmail, Outlook, Thunderbird, Apple Mail) include the
previous message as quoted text when the user hits "Reply". The quoted
portion is usually delimited in one of two ways:

1. Line-prefix quoting (RFC 3676):
       > Prezado, recebemos sua solicitação...
       > Atenciosamente,

2. An attribution line followed by the original message:
       Em qui., 9 de abr. de 2026 às 08:44, Fulano <x@y.com> escreveu:
       On Thu, Apr 9, 2026 at 8:44 AM, Fulano <x@y.com> wrote:
       Em 09/04/2026 08:44, Fulano escreveu:

Without this split, the LLM sees a mixed blob of the student's new reply
and the secretariat's previous message, and may confuse who is asking
what. We use this module to present the two parts to the LLM as distinct
sections of the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Attribution lines that mark the start of the quoted history.
# Portuguese (Gmail PT-BR) and English variants, plus a generic date-prefix form.
# Note: we use [\s\S] instead of . so the patterns can span line breaks —
# Gmail frequently wraps long attribution lines at the email address angle
# bracket, e.g.:
#     Em qui., 9 de abr. de 2026 às 09:01, Secretaria do Curso <
#     design@ufpr.br> escreveu:
_ATTRIBUTION_PATTERNS = [
    # "Em qui., 9 de abr. de 2026 às 08:44, Fulano <x@y.com> escreveu:"
    re.compile(r"^[ \t]*Em\s+[\s\S]{0,300}?\bescreveu:\s*$", re.IGNORECASE | re.MULTILINE),
    # "On Thu, Apr 9, 2026 at 8:44 AM, Fulano <x@y.com> wrote:"
    re.compile(r"^[ \t]*On\s+[\s\S]{0,300}?\bwrote:\s*$", re.IGNORECASE | re.MULTILINE),
    # Outlook-style "De: ... Enviada em: ... Para: ..."
    re.compile(
        r"^[ \t]*(?:De|From):\s+.{1,200}?$\s*(?:Enviad[ao]\s+em|Sent):\s+.{1,200}?$",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Generic "-----Original Message-----" (older Outlook)
    re.compile(
        r"^[ \t]*-{2,}\s*(?:Original\s+Message|Mensagem\s+original)\s*-{2,}\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
]


@dataclass(frozen=True)
class SplitBody:
    """Result of splitting an email body into its current reply + quoted history.

    Attributes:
        new_reply: The new message the sender wrote (the part above the
            quoted history). Empty if the entire body is quoted text.
        quoted_history: The previous message(s) in the thread, in their
            original order (may be multi-level). Empty if there is no
            quoted content.
    """

    new_reply: str
    quoted_history: str

    @property
    def has_history(self) -> bool:
        return bool(self.quoted_history.strip())


def split_reply_and_quoted(body: str) -> SplitBody:
    """Split an email body into (new_reply, quoted_history).

    The algorithm:
      1. Look for an attribution line ("Em ... escreveu:", "On ... wrote:",
         "-----Original Message-----"). If found, everything above is the
         new reply and the attribution+below is the quoted history.
      2. Otherwise, fall back to splitting on the first run of lines that
         start with ``> `` or ``>`` (RFC 3676 quoting).
      3. If neither marker is present, return the whole body as new_reply
         and empty quoted_history.

    The new_reply is trimmed of trailing whitespace.
    """
    if not body:
        return SplitBody(new_reply="", quoted_history="")

    # Strategy 1: attribution line
    earliest_attr: tuple[int, int] | None = None  # (match_start, match_end)
    for pattern in _ATTRIBUTION_PATTERNS:
        m = pattern.search(body)
        if m and (earliest_attr is None or m.start() < earliest_attr[0]):
            earliest_attr = (m.start(), m.end())

    if earliest_attr is not None:
        start, _ = earliest_attr
        new_reply = body[:start].rstrip()
        quoted = body[start:].strip()
        return SplitBody(new_reply=new_reply, quoted_history=quoted)

    # Strategy 2: RFC 3676 quoted lines — find the first contiguous block
    # of lines that start with ">".
    lines = body.splitlines()
    first_quote_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith(">"):
            first_quote_idx = i
            break

    if first_quote_idx is not None:
        # Walk backward from first_quote to skip any single blank line
        # (common pattern: blank line between reply and first ">").
        cutoff = first_quote_idx
        if cutoff > 0 and not lines[cutoff - 1].strip():
            cutoff -= 1
        new_reply = "\n".join(lines[:cutoff]).rstrip()
        quoted = "\n".join(lines[first_quote_idx:]).strip()
        return SplitBody(new_reply=new_reply, quoted_history=quoted)

    # Strategy 3: no quoted history detected
    return SplitBody(new_reply=body.rstrip(), quoted_history="")


def format_for_prompt(split: SplitBody, max_history_chars: int = 4000) -> str:
    """Format a SplitBody for inclusion in an LLM prompt.

    Presents the new reply and quoted history as explicitly labeled sections
    so the LLM understands which part is the current request vs. the prior
    message in the thread.

    Args:
        split: Result of ``split_reply_and_quoted``.
        max_history_chars: Truncate the quoted history to this many chars
            (counted from the beginning — the most recent prior message is
            usually at the top of the quoted block).
    """
    if not split.has_history:
        return split.new_reply

    quoted = split.quoted_history
    truncated_suffix = ""
    if len(quoted) > max_history_chars:
        quoted = quoted[:max_history_chars]
        truncated_suffix = "\n[... histórico truncado ...]"

    return (
        "=== NOVA MENSAGEM DO REMETENTE (o que ele está pedindo AGORA) ===\n"
        f"{split.new_reply or '(mensagem vazia — apenas citou o histórico)'}\n\n"
        "=== HISTÓRICO (mensagens anteriores nesta thread — apenas referência) ===\n"
        f"{quoted}{truncated_suffix}"
    )
