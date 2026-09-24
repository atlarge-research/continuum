"""Compatibility entry point; implementation lives in the reporting package."""
# Public imports preserve existing script and library entry points.
# pylint: disable=unused-import
from reporting.assembly import main, render_report, write_report


if __name__ == "__main__":
    main()
