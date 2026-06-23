"""Country-axis isolation validation — prevents Italy-specific axes leaking to other targets."""

from __future__ import annotations

from typing import Any

ITALY_SPECIFIC_AXES = {"coalition", "eu_role", "region", "china_italy_relations"}


def validate_country_axes_isolation(
    target_id: str,
    classification: dict[str, Any],
) -> None:
    """验证分类结果中的 country_axes 不包含意大利专有轴。

    在非意大利目标的 ClassifierRules.apply_to_event() 中调用，
    防止意大利专有轴泄漏到其他国家事件。

    Args:
        target_id: 当前目标 ID。
        classification: 事件分类结果 dict。

    Raises:
        ValueError: 非意大利目标包含意大利专有轴。
    """
    if target_id == "italy":
        return
    country_axes = classification.get("country_axes", {})
    for axis in ITALY_SPECIFIC_AXES:
        if axis in country_axes:
            raise ValueError(
                f"目标 '{target_id}' 的分类结果含意大利专有轴 '{axis}'，"
                f"请检查 config/country-axes/{target_id}.yaml"
            )
