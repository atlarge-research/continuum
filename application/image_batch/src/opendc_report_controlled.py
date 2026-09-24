"""Compatibility entry point; implementation lives in the reporting package."""
# Public imports preserve existing script and library entry points.
# pylint: disable=unused-import
from reporting.controlled import (
    SCHEMA,
    action_reference,
    lifecycle_rows,
    main,
    render_pages,
    timing_summary,
    validate_comparisons,
    write_report,
)


if __name__ == "__main__":
    main()
