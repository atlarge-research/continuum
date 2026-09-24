"""Compatibility entry point; implementation lives in the reporting package."""
# Public imports preserve existing script and library entry points.
# pylint: disable=unused-import
from analyze_run_core import (
    STREAMS,
    analyze,
    compact_alignment,
    describe,
    endpoint_run,
    number,
    range_series,
    read_jsonl,
    require,
    seconds,
    unique,
    write_csv,
)
from reporting.analyzer import format_value, main, render, summary_text


if __name__ == "__main__":
    raise SystemExit(main())
