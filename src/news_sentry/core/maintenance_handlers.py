"""Extracted handler logic for Maintenance admin endpoints.

Each async function accepts ``store`` and ``data_dir`` as its first parameter(s),
followed by the query/path/body parameters.
This keeps the handler bodies testable independently of the FastAPI ``create_app()`` closure.

Originally extracted from ``api_server.py`` lines ~4970-5052.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import HTTPException

# ═══════════════════════════════════════════════════════════════════════
# Maintenance
# ═══════════════════════════════════════════════════════════════════════


async def maintenance_draft_diagnostics(
    draft_diagnostics_fn: Any,
    data_dir: Any,
    target_id: str,
) -> dict[str, Any]:
    """只读诊断 draft 文件与运行时索引的一致性。"""
    return cast("dict[str, Any]", await draft_diagnostics_fn(data_dir, target_id))


async def maintenance_archive_duplicate_drafts(
    archive_fn: Any,
    data_dir: Any,
    target_id: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """将重复 event_id 的多余 draft 文件归档，保留可公开读取的 canonical 文件。"""
    return cast("dict[str, Any]", await archive_fn(data_dir, target_id, dry_run=dry_run))


async def maintenance_prune(
    store: Any,
    target_id: str,
    max_age_days: int = 30,
) -> Any:  # returns PruneResponse-compatible dict
    """手动触发数据清理。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not available")
    result = await store.prune_old_data(target_id, max_age_days=max_age_days)
    return {"target_id": target_id, **result}


async def maintenance_backup(
    store: Any,
) -> Any:  # returns BackupResponse-compatible dict
    """手动触发数据库备份。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not available")
    backup_dir = store.db_path.parent / "backups"
    backup_path = await store.backup_db(backup_dir)
    size = backup_path.stat().st_size if backup_path.exists() else 0
    return {"backup_path": str(backup_path), "size_bytes": size}


async def list_backups(
    store: Any,
) -> dict[str, Any]:
    """列出可用备份。"""
    if store is None:
        return {"backups": []}
    backup_dir = store.db_path.parent / "backups"
    if not backup_dir.exists():
        return {"backups": []}
    backups = []
    for f in sorted(backup_dir.glob("state_*.db"), reverse=True):
        backups.append(
            {
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "created_at": f.stat().st_ctime,
            }
        )
    return {"backups": backups}


async def restore_backup(
    store: Any,
    filename: str,
) -> dict[str, Any]:
    """从备份恢复数据库。"""
    if store is None:
        raise HTTPException(status_code=503, detail="Store not available")
    backup_dir = store.db_path.parent / "backups"
    backup_path = backup_dir / filename
    if not backup_path.exists() or not filename.startswith("state_"):
        raise HTTPException(status_code=404, detail="Backup not found")
    # 安全检查：防止路径遍历
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # 先备份当前数据库
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    current_backup = store.db_path.parent / f"state_pre_restore_{ts}.db"
    shutil.copy2(str(store.db_path), str(current_backup))
    # 关闭当前连接
    await store.close()
    # 替换数据库文件
    shutil.copy2(str(backup_path), str(store.db_path))
    # 重新初始化
    await store.initialize()
    return {"status": "restored", "restored_from": filename}
