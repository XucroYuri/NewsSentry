"""Config package — ConfigLoader, ResolvedConfig, and validation utilities.

Submodules:
- models: ResolvedConfig Pydantic model
- loader: ConfigLoader class (YAML, JSON Schema, reference resolution)
- country_axes: country-specific axis isolation validation
"""

from __future__ import annotations

from news_sentry.core.config.country_axes import (
    ITALY_SPECIFIC_AXES,
    TARGET_SPECIFIC_AXES,
    validate_country_axes_isolation,
)
from news_sentry.core.config.loader import ConfigLoader
from news_sentry.core.config.models import ResolvedConfig

__all__ = [
    "ConfigLoader",
    "ITALY_SPECIFIC_AXES",
    "ResolvedConfig",
    "TARGET_SPECIFIC_AXES",
    "validate_country_axes_isolation",
]
