"""Compatibility entry point; implementation lives in the reporting package."""
# Public imports preserve existing script and library entry points.
# pylint: disable=unused-import
from reporting.measured import SCHEMA, main, measured_groups, prepare_measured


if __name__ == "__main__":
    main()
