"""Brazilian date parsing helpers shared across modules.

Two parse variants exist because callers want different return types:

- :func:`parse_br_date_to_str` returns ``"DD/MM/YYYY"`` and accepts both
  numeric and extenso ("30 de junho de 2026") inputs. Used by
  ``procedures/playbook.py`` when extracting variables from email body /
  attachment text.
- :func:`parse_br_date_to_date` returns ``datetime.date`` and accepts only
  numeric ``DD/MM/YYYY``. Used by ``procedures/checkers.py`` for date
  arithmetic against ``date.today()``.

The duplication is intentional — chaining ``str → date`` would force
checkers to handle ``None`` twice for one logical operation.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

DATE_RE = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")

MESES_PT: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

DATE_EXTENSO_RE = re.compile(
    r"\b(\d{1,2})\s+de\s+"
    r"(janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|"
    r"agosto|setembro|outubro|novembro|dezembro)"
    r"\s+de\s+(\d{4})\b",
    re.IGNORECASE,
)


def parse_br_date_to_str(text: str) -> str | None:
    """Normalize a Brazilian date (numeric or extenso) to ``DD/MM/YYYY``.

    Returns ``None`` if no recognizable date is found. Used when extracting
    dates from PDFs/emails that sometimes spell dates out
    ("30 de junho de 2026") rather than use DD/MM/YYYY.
    """
    if not text:
        return None
    m = DATE_RE.search(text)
    if m:
        return m.group(1)
    m = DATE_EXTENSO_RE.search(text)
    if m:
        day = int(m.group(1))
        mes_key = m.group(2).lower().replace("ç", "c")
        mes = MESES_PT.get(mes_key)
        if mes:
            return f"{day:02d}/{mes:02d}/{int(m.group(3))}"
    return None


def parse_br_date_to_date(s: str) -> date | None:
    """Parse ``DD/MM/YYYY`` into a :class:`datetime.date`.

    Returns ``None`` when the string is empty or doesn't match the format.
    """
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def working_days_between(start: date, end: date) -> int:
    """Count working days (Mon-Fri) between two dates, exclusive of start,
    inclusive of end. Does NOT account for national/academic holidays.
    """
    if end <= start:
        return 0
    days = 0
    cur = start + timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:  # 0=Mon .. 4=Fri
            days += 1
        cur += timedelta(days=1)
    return days
