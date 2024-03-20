"""Deterministic report renderers with no timestamps or source filenames."""

import json
import re
from dataclasses import asdict
from html import escape

from .changes import SEVERITY_ORDER, Change, sort_changes


def summary(changes: list[Change]) -> dict[str, int]:
    counts = dict.fromkeys(SEVERITY_ORDER, 0)
    for change in changes:
        counts[change.severity] += 1
    return counts


def json_report(changes: list[Change]) -> str:
    return json.dumps({
        "report_version": 1,
        "summary": summary(changes),
        "changes": [asdict(change) for change in sort_changes(changes)],
    }, indent=2) + "\n"


def visible(value: str) -> str:
    return "".join(char if char.isprintable() else json.dumps(char)[1:-1] for char in value)


def code_span(value: str) -> str:
    text = visible(value)
    fence = "`" * (1 + max((len(run) for run in re.findall(r"`+", text)), default=0))
    return f"{fence} {text} {fence}"


def markdown_text(value: str) -> str:
    return re.sub(r"([\\`*_\[\]~!])", r"\\\1", escape(visible(value), quote=False))


def markdown_report(changes: list[Change]) -> str:
    counts = summary(changes)
    lines = ["# OpenAPI compatibility report", "",
             f"{counts['breaking']} breaking · {counts['review']} review · {counts['non-breaking']} non-breaking"]
    if not changes:
        lines.extend(["", "No findings in the supported comparisons."])
    ordered = sort_changes(changes)
    for severity, title in (("breaking", "Breaking"), ("review", "Review"), ("non-breaking", "Non-breaking")):
        if not counts[severity]:
            continue
        lines.extend(["", f"## {title}", ""])
        for change in ordered:
            if change.severity != severity:
                continue
            lines.append(f"- {code_span(change.code)} — {markdown_text(change.message)}")
            if change.operation and change.operation not in (change.before, change.after):
                lines.append(f"  - Operation: {code_span(change.operation)}")
            if change.before is not None:
                lines.append(f"  - Before: {code_span(change.before)}")
            if change.after is not None:
                lines.append(f"  - After: {code_span(change.after)}")
    return "\n".join(lines) + "\n"
