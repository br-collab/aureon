"""US equities session calendar, read from Atreides' committed calendar file.

aureon does not keep its own holiday or early-close list. It vendors the one file
Project-Atreides publishes (``atreides/deadlines/calendars/us_equities.json``) and checks
its SHA-256 against ``source.json`` on every load, so a hand edit here fails closed.
A date in a year the file does not cover raises ``CalendarIndeterminateError``; it is
never read as an ordinary trading day.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, time
from functools import lru_cache
from pathlib import Path

_FOLDER = Path(__file__).with_name("vendor") / "atreides-calendar"


class CalendarIndeterminateError(ValueError):
    """The vendored calendar cannot decide this date."""


@dataclass(frozen=True, slots=True)
class SessionCalendar:
    holidays: dict[int, frozenset[date]]
    early_closes: dict[int, frozenset[date]]
    regular_close: time
    early_close: time
    source_commit: str

    def session_close(self, value: date) -> time:
        if value.year not in self.holidays or value.year not in self.early_closes:
            raise CalendarIndeterminateError(f"no session data for {value.year}")
        if value.weekday() >= 5 or value in self.holidays[value.year]:
            raise ValueError(f"US equities market is closed on {value.isoformat()}")
        if value in self.early_closes[value.year]:
            return self.early_close
        return self.regular_close


@lru_cache(maxsize=1)
def load_us_equities_calendar() -> SessionCalendar:
    source = json.loads((_FOLDER / "source.json").read_text(encoding="utf-8"))
    raw = (_FOLDER / "us_equities.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != source["sha256"]:
        raise CalendarIndeterminateError("vendored calendar does not match its pinned checksum")
    document = json.loads(raw)
    return SessionCalendar(
        holidays={
            int(year): frozenset(date.fromisoformat(day) for day in days)
            for year, days in document["holidays"].items()
        },
        early_closes={
            int(year): frozenset(date.fromisoformat(day) for day in days)
            for year, days in document.get("early_closes", {}).items()
        },
        regular_close=time.fromisoformat(document["regular_close"]),
        early_close=time.fromisoformat(document["early_close"]),
        source_commit=str(source["commit"]),
    )
