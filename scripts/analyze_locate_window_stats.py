"""Analyze locate CLIP window effectiveness from search telemetry."""
from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.services.locate_window_analysis import (
    format_locate_window_report,
    format_version_decision_report,
    load_and_analyze_locate_window_stats,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze locate CLIP window telemetry buckets.")
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Reload telemetry from disk before analysis.",
    )
    parser.add_argument(
        "--no-record-history",
        action="store_true",
        help="Do not append this run to analysis history.",
    )
    parser.add_argument(
        "--stability-window",
        type=int,
        default=5,
        help="Number of recent history snapshots used for temporal stability.",
    )
    parser.add_argument(
        "--version-report",
        action="store_true",
        help="Print one-page version decision template instead of full diagnostics.",
    )
    args = parser.parse_args()

    analysis = load_and_analyze_locate_window_stats(
        reload=bool(args.reload),
        record_history=not bool(args.no_record_history),
        stability_window=max(1, int(args.stability_window)),
    )
    if args.version_report:
        print(format_version_decision_report(analysis))
    else:
        print(format_locate_window_report(analysis))


if __name__ == "__main__":
    main()
