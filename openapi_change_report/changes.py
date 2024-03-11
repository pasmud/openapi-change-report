"""Shared report records and ordering."""

from dataclasses import dataclass

SEVERITY_ORDER = {"breaking": 0, "review": 1, "non-breaking": 2}


@dataclass(frozen=True)
class Change:
    severity: str
    code: str
    message: str
    before: str | None = None
    after: str | None = None
    operation: str | None = None


def sort_changes(changes: list[Change]) -> list[Change]:
    return sorted(changes, key=lambda c: (SEVERITY_ORDER[c.severity], c.after or c.before or "",
                                         c.code, c.operation or "", c.before or "", c.after or "", c.message))
