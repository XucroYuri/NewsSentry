"""Implements: docs/spec/phase-3-kernel-mvp.md §3.1, ADR-0016

CLI entry point for `python -m news_sentry.cli`.
The click group lives in __init__.py to avoid RuntimeWarning on module execution.
"""
if __name__ == "__main__":
    from news_sentry.cli import main
    main()
