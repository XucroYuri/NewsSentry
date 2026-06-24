"""Target-specific axis isolation validation.

Prevents target-exclusive axes from leaking to other targets.

每个 target 可在其 config/targets/{target_id}.yaml 的 classification.specific_axes
中声明仅本 target 有意义的轴。其他 target 的分类结果不允许包含这些轴。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 向后兼容别名：意大利 4 个独占轴
# 新代码应从 target config 的 classification.specific_axes 读取
ITALY_SPECIFIC_AXES = frozenset({"coalition", "eu_role", "region", "china_italy_relations"})

TARGET_SPECIFIC_AXES = ITALY_SPECIFIC_AXES  # 向后兼容别名

_CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"


def _load_target_specific_axes(target_id: str) -> frozenset[str]:
    """从 config/targets/{target_id}.yaml 加载 target 独占轴。

    若配置文件不存在或未声明 specific_axes，返回空 frozenset
    （即该 target 对所有轴开放）。
    """
    target_yaml = _CONFIG_DIR / "targets" / f"{target_id}.yaml"
    if not target_yaml.is_file():
        return frozenset()

    try:
        data = yaml.safe_load(target_yaml.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        logger.warning("无法解析 target 配置 %s", target_yaml)
        return frozenset()

    if not isinstance(data, dict):
        return frozenset()

    classification = data.get("classification")
    if not isinstance(classification, dict):
        return frozenset()

    axes = classification.get("specific_axes")
    if isinstance(axes, list):
        return frozenset(str(a) for a in axes)

    return frozenset()


def validate_country_axes_isolation(
    target_id: str,
    classification: dict[str, Any],
) -> None:
    """验证分类结果中的 country_axes 不包含其他 target 的独占轴。

    在 ClassifierRules.apply_to_event() 中调用，防止 target 独占轴
    泄漏到其他 target 的事件。

    Args:
        target_id: 当前目标 ID。
        classification: 事件分类结果 dict。

    Raises:
        ValueError: 当前 target 的分类结果包含其他 target 的独占轴。
    """
    all_specific_axes = _load_all_specific_axes_except(target_id)
    if not all_specific_axes:
        return

    country_axes = classification.get("country_axes", {})
    for axis in all_specific_axes:
        if axis in country_axes:
            raise ValueError(
                f"目标 '{target_id}' 的分类结果含 target 独占轴 '{axis}'，请检查 config 配置"
            )


def _load_all_specific_axes_except(target_id: str) -> frozenset[str]:
    """加载所有其他 target 声明的独占轴合集。

    当前 target 的独占轴会从集合中排除（因为当前 target 有权限使用）。
    """
    targets_dir = _CONFIG_DIR / "targets"
    if not targets_dir.is_dir():
        return frozenset()

    all_axes: set[str] = set()
    for yf in sorted(targets_dir.glob("*.yaml")):
        other_id = yf.stem
        if other_id == target_id:
            continue
        all_axes |= _load_target_specific_axes(other_id)

    return frozenset(all_axes)
