"""Command-line entry point for local comparisons."""

import argparse
import sys
from pathlib import Path

from .compare import compare
from .document import InputError, load
from .report import json_report, markdown_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="openapi-change-report",
                                     description="Review compatibility between two local OpenAPI 3 files.")
    parser.add_argument("before", type=Path, help="baseline .json, .yaml or .yml file")
    parser.add_argument("after", type=Path, help="candidate .json, .yaml or .yml file")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown", help="report format")
    parser.add_argument("--fail-on", choices=("breaking", "review", "never"), default="breaking",
                        help="exit 1 on breaking findings (default), breaking or review, or neither")
    args = parser.parse_args(argv)

    documents = []
    for side in ("before", "after"):
        path = getattr(args, side)
        try:
            documents.append(load(path))
        except InputError as exc:
            print(f"{parser.prog}: {side} {str(path)!r}: {exc}", file=sys.stderr)
            return 2
    try:
        changes = compare(*documents)
    except InputError as exc:
        print(f"{parser.prog}: {exc}", file=sys.stderr)
        return 2

    sys.stdout.write(json_report(changes) if args.format == "json" else markdown_report(changes))
    failures = {"breaking": {"breaking"}, "review": {"breaking", "review"}, "never": set()}
    return int(any(change.severity in failures[args.fail_on] for change in changes))
