"""Language helpers shared by collectors."""

from __future__ import annotations

from typing import Any

from news_sentry.models.newsevent import Language


def coerce_language(value: Any, default: Language = Language.MIXED) -> Language:  # noqa: ANN401
    """Convert source/API language strings to the NewsEvent language contract."""
    if isinstance(value, Language):
        return value
    if value is None:
        return default
    code = str(value).strip().lower().replace("_", "-").split("-", 1)[0]
    if not code:
        return default
    try:
        return Language(code)
    except ValueError:
        return default
