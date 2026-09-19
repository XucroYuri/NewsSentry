from __future__ import annotations

import copy
import json
import sqlite3
import tomllib
from pathlib import Path

import pytest
from tools.cloudflare_runtime_contract import EXPECTED_MIGRATION_RECEIPTS

from tools import cloudflare_preview_guard as guard

ROOT = Path(__file__).resolve().parents[2]


def test_select_preview_d1_requires_exact_unique_database() -> None:
    payload = {
        "result": [
            {"uuid": "11111111-1111-4111-8111-111111111111", "name": "ns-db"},
            {
                "uuid": "22222222-2222-4222-8222-222222222222",
                "name": "ns-db-preview",
            },
        ]
    }

    selected = guard.select_preview_d1_database(payload)

    assert selected.database_id == "22222222-2222-4222-8222-222222222222"
    assert selected.database_name == "ns-db-preview"


def test_select_preview_d1_missing_has_dedicated_exit_code() -> None:
    with pytest.raises(guard.PreviewDatabaseMissing) as excinfo:
        guard.select_preview_d1_database({"result": [{"uuid": "x", "name": "ns-db"}]})

    assert excinfo.value.exit_code == guard.PREVIEW_D1_MISSING_EXIT


def test_select_preview_d1_rejects_ambiguous_or_invalid_payloads() -> None:
    with pytest.raises(guard.PreviewGuardError):
        guard.select_preview_d1_database(
            [
                {"uuid": "1", "name": "ns-db-preview"},
                {"uuid": "2", "name": "ns-db-preview"},
            ]
        )

    with pytest.raises(guard.PreviewGuardError):
        guard.select_preview_d1_database({"unexpected": "shape"})


REAL_WRANGLER = ROOT / "frontend" / "cloudflare" / "wrangler.toml"
SYNTHETIC_PLACEHOLDER = "00000000-0000-4000-8000-000000000000"
SYNTHETIC_PREVIEW_D1 = "22222222-2222-4222-8222-222222222222"


def _kv_bindings(node: object) -> list[dict[str, object]]:
    """递归收集配置中所有 ``kv_namespaces`` 绑定（顶层与各 env 下）。"""
    found: list[dict[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "kv_namespaces" and isinstance(value, list):
                found.extend(item for item in value if isinstance(item, dict))
            else:
                found.extend(_kv_bindings(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_kv_bindings(item))
    return found


def test_no_placeholder_kv_binding_is_committed() -> None:
    """回归防线：不得提交占位 KV id。

    占位 id 被 Cloudflare 拒绝 —— ``KV namespace '0000…' is not valid [code: 10042]`` ——
    曾使**生产完全不可部署**（2026-08-05 至 2026-09-19，见
    ``docs/spec/phases/L1-instrument.md §9``）。

    若将来确需 KV：必须使用**真实** namespace id，或由流水线注入。
    """
    data = tomllib.loads(REAL_WRANGLER.read_text(encoding="utf-8"))
    offenders = [
        binding
        for binding in _kv_bindings(data)
        if SYNTHETIC_PLACEHOLDER in (binding.get("id"), binding.get("preview_id"))
    ]
    assert not offenders, f"禁止提交占位 KV id（Cloudflare 以 10042 拒绝）：{offenders}"


def test_render_preview_config_uses_the_real_wrangler_toml(tmp_path: Path) -> None:
    """INV-D：守卫读取真实制品，因此必须针对真实制品测试。

    首版守卫假设占位符全局唯一，而它的测试用的是**恰好一个占位符**的合成 TOML；
    真实配置有 3 处（KV 的 id 与 preview_id 复用了 D1 的占位 UUID），
    故障因此隐藏 45 天（见 docs/spec/phases/L1-instrument.md §7.4）。
    """
    output = tmp_path / "wrangler.preview.generated.toml"

    guard.render_preview_config(REAL_WRANGLER, output, database_id=SYNTHETIC_PREVIEW_D1)

    original = tomllib.loads(REAL_WRANGLER.read_text(encoding="utf-8"))
    rendered = tomllib.loads(output.read_text(encoding="utf-8"))

    # 1) 目标字段已替换，且该表项的其余字段未变
    preview_d1 = rendered["env"]["preview"]["d1_databases"][0]
    assert preview_d1["database_id"] == SYNTHETIC_PREVIEW_D1
    assert preview_d1["binding"] == "DB"
    assert preview_d1["database_name"] == "ns-db-preview"

    # 2) 生产资源零改动
    assert rendered["d1_databases"][0]["database_id"] == original["d1_databases"][0]["database_id"]
    assert rendered["r2_buckets"][0] == original["r2_buckets"][0]

    # 3) KV 配置不被本函数触碰：渲染后的 KV 绑定集合与源配置完全一致
    #    （占位 KV 块已于 2026-09-19 移除，见 docs/spec/phases/L1-instrument.md §9；
    #     此处不再断言"占位符保留"，改为断言"渲染不改变 KV 配置"）
    assert _kv_bindings(rendered) == _kv_bindings(original)

    # 4) 除目标字段外，整份配置深度相等（"有没有多改"的断言）
    expected = copy.deepcopy(original)
    expected["env"]["preview"]["d1_databases"][0]["database_id"] = SYNTHETIC_PREVIEW_D1
    assert rendered == expected


def test_render_preview_config_changes_exactly_one_line(tmp_path: Path) -> None:
    """渲染是定点替换：真实配置的字节级 diff 应恰好一行。"""
    output = tmp_path / "wrangler.preview.generated.toml"

    guard.render_preview_config(REAL_WRANGLER, output, database_id=SYNTHETIC_PREVIEW_D1)

    before = REAL_WRANGLER.read_text(encoding="utf-8").splitlines()
    after = output.read_text(encoding="utf-8").splitlines()
    assert len(before) == len(after)
    changed = [index for index, (a, b) in enumerate(zip(before, after, strict=True)) if a != b]
    assert len(changed) == 1
    assert after[changed[0]] == f'database_id = "{SYNTHETIC_PREVIEW_D1}"'


def test_render_preview_config_happy_path_on_synthetic_config(tmp_path: Path) -> None:
    source = tmp_path / "wrangler.toml"
    output = tmp_path / "wrangler.preview.toml"
    source.write_text(
        "\n".join(
            [
                "[[d1_databases]]",
                'binding = "DB"',
                'database_name = "ns-db"',
                'database_id = "35a52961-e7e1-41ef-934e-7a63882ba465"',
                "",
                "[[env.preview.d1_databases]]",
                'binding = "DB"',
                'database_name = "ns-db-preview"',
                f'database_id = "{SYNTHETIC_PLACEHOLDER}"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    guard.render_preview_config(source, output, database_id=SYNTHETIC_PREVIEW_D1)

    rendered = tomllib.loads(output.read_text(encoding="utf-8"))
    assert rendered["env"]["preview"]["d1_databases"][0]["database_id"] == SYNTHETIC_PREVIEW_D1
    assert rendered["d1_databases"][0]["database_id"] == "35a52961-e7e1-41ef-934e-7a63882ba465"


def test_render_preview_config_rejects_non_uuid_target(tmp_path: Path) -> None:
    output = tmp_path / "out.toml"
    with pytest.raises(guard.PreviewGuardError):
        guard.render_preview_config(REAL_WRANGLER, output, database_id="not-a-uuid")


@pytest.mark.parametrize(
    "body",
    [
        # 缺少 [[env.preview.d1_databases]] 段
        '[[d1_databases]]\ndatabase_id = "00000000-0000-4000-8000-000000000000"\n',
        # 该段存在但 database_id 已是真实值（重复渲染应被拒）
        "[[env.preview.d1_databases]]\n"
        'database_id = "22222222-2222-4222-8222-222222222222"\n',
        # 该段存在但没有 database_id 行
        '[[env.preview.d1_databases]]\nbinding = "DB"\n',
        # 该段有两个表项 → 歧义
        "[[env.preview.d1_databases]]\n"
        f'database_id = "{SYNTHETIC_PLACEHOLDER}"\n'
        "[[env.preview.d1_databases]]\n"
        f'database_id = "{SYNTHETIC_PLACEHOLDER}"\n',
        # 非法 TOML
        "[[env.preview.d1_databases]\ndatabase_id = broken\n",
    ],
)
def test_render_preview_config_fails_closed(tmp_path: Path, body: str) -> None:
    source = tmp_path / "wrangler.toml"
    source.write_text(body, encoding="utf-8")

    with pytest.raises(guard.PreviewGuardError):
        guard.render_preview_config(
            source, tmp_path / "out.toml", database_id=SYNTHETIC_PREVIEW_D1
        )


def test_build_preview_seed_sql_contains_fresh_event_ops_and_snapshots(
    tmp_path: Path,
) -> None:
    sql = guard.build_preview_seed_sql(
        now_iso="2026-08-02T00:00:00Z",
        deploy_commit="abc123",
        run_id="run-7",
    )

    assert not sql.lstrip().startswith("#")
    assert sql.startswith("INSERT OR REPLACE INTO targets")
    assert "preview-smoke-run-7" in sql
    assert "INSERT OR REPLACE INTO events" in sql
    assert "INSERT OR REPLACE INTO ops_state" in sql
    assert "last:collect-cycle" in sql
    assert "last:public-translation-cycle" in sql
    assert "last:refresh-public-quality" in sql
    assert "INSERT OR REPLACE INTO public_read_snapshots" in sql
    assert "news:featured:v1:page_size=20" in sql
    assert "bootstrap:featured:v1:page_size=20" in sql
    assert "facets:v1" in sql
    assert "regions:active:v1" in sql
    assert "abc123" in sql

    connection = sqlite3.connect(tmp_path / "preview.db")
    try:
        connection.executescript(
            (ROOT / "frontend/cloudflare/db/schema.sql").read_text(encoding="utf-8")
        )
        connection.executescript(sql)
        row = connection.execute(
            "SELECT target_id, config_version FROM source_runtime_state "
            "WHERE source_id = 'preview-seed'"
        ).fetchone()
        migration_receipts = {
            result[0]
            for result in connection.execute(
                "SELECT migration_id FROM runtime_migration_receipts"
            ).fetchall()
        }
        snapshot_sizes = connection.execute(
            "SELECT payload_json, payload_bytes FROM public_read_snapshots"
        ).fetchall()
    finally:
        connection.close()

    assert row == ("preview", "abc123")
    assert migration_receipts == set(EXPECTED_MIGRATION_RECEIPTS)
    assert all(
        len(payload_json.encode("utf-8")) == payload_bytes
        for payload_json, payload_bytes in snapshot_sizes
    )


def test_parse_preview_deploy_receipt_validates_worker_env_and_https_target(tmp_path: Path) -> None:
    receipt = tmp_path / "wrangler-output.ndjson"
    receipt.write_text(
        "\n".join(
            [
                json.dumps({"type": "log", "message": "deploying"}),
                json.dumps(
                    {
                        "worker_name": "news-sentry-api-preview",
                        "wrangler_environment": "preview",
                        "targets": [
                            {
                                "url": "https://news-sentry-api-preview.example.workers.dev"
                            }
                        ],
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    parsed = guard.parse_preview_deploy_receipt(receipt)

    assert parsed.api_url == "https://news-sentry-api-preview.example.workers.dev"
    assert parsed.worker_name == "news-sentry-api-preview"
    assert parsed.environment == "preview"


def test_parse_preview_deploy_receipt_rejects_wrong_worker_or_non_https(tmp_path: Path) -> None:
    receipt = tmp_path / "wrangler-output.ndjson"
    receipt.write_text(
        json.dumps(
            {
                "worker_name": "news-sentry-api",
                "wrangler_environment": "preview",
                "targets": [{"url": "http://example.workers.dev"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(guard.PreviewGuardError):
        guard.parse_preview_deploy_receipt(receipt)


def test_parse_preview_deploy_receipt_requires_real_wrangler_env_and_workers_dev(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "wrangler-output.ndjson"
    receipt.write_text(
        json.dumps(
            {
                "worker_name": "news-sentry-api-preview",
                "environment": "preview",
                "targets": ["https://news-sentry-api-preview.example.workers.dev"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(guard.PreviewGuardError):
        guard.parse_preview_deploy_receipt(receipt)

    receipt.write_text(
        json.dumps(
            {
                "worker_name": "news-sentry-api-preview",
                "wrangler_environment": "preview",
                "targets": ["https://attacker.example/preview"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(guard.PreviewGuardError):
        guard.parse_preview_deploy_receipt(receipt)
