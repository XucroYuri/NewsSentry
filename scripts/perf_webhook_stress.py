"""R4.4 性能压测脚本 — 持续 Webhook 推送 + EventBus 发布场景。

模拟: N 个 webhook 事件持续推送，测量 EventBus + NotificationEngine
在持续负载下的 CPU 和内存消耗。

用法:
    uv run python scripts/perf_webhook_stress.py --events 1000 --concurrency 10

不依赖 FastAPI TestClient — 直接调用 EventBus + NotificationEngine 核心逻辑。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

# 将项目根加入 sys.path（脚本可能在项目外运行）
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from news_sentry.core.async_store import AsyncStore  # noqa: E402
from news_sentry.core.event_bus import EventBus  # noqa: E402
from news_sentry.core.notification_engine import NotificationEngine  # noqa: E402


async def _seed_rules(store: AsyncStore) -> None:
    """添加测试通知规则。"""
    rules = [
        {
            "id": f"perf-rule-{i}",
            "enabled": True,
            "watch": {
                "target_ids": ["italy"],
                "min_value_score": 50,
                "entities": [],
                "sentiment": [],
            },
            "action": {"channels": ["browser"], "throttle_seconds": 0},
        }
        for i in range(5)
    ]
    for r in rules:
        await store.upsert_notification_rule(r)


async def _run_stress(
    events: int,
    concurrency: int,
    output: str | None,
) -> dict:
    """运行压力测试。"""
    import resource

    bus = EventBus()

    # 初始化 AsyncStore（内存数据库）
    store = AsyncStore(":memory:")
    await store.initialize()
    await _seed_rules(store)

    # 启动 NotificationEngine
    engine = NotificationEngine(store, bus)
    await engine.start()

    # 统计
    alerts_received: list[dict] = []
    async def alert_collector(topic: str, payload: dict) -> None:
        alerts_received.append(payload)

    await bus.subscribe("alert.triggered.browser", alert_collector)

    # ── 开始压测 ──
    sem = asyncio.Semaphore(concurrency)
    start_time = time.time()

    async def push_one(i: int) -> None:
        async with sem:
            await bus.publish(
                "news.judged.italy",
                {
                    "event_id": f"ev-perf-{i}",
                    "target_id": "italy",
                    "news_value_score": 85,
                    "sentiment": "negative",
                    "entity_names": ["Meloni"],
                    "title": f"Stress test event #{i}",
                    "judged_at_ts": time.time(),
                },
            )
            # 给消费者一点时间处理
            await asyncio.sleep(0.001)

    tasks = [push_one(i) for i in range(events)]
    await asyncio.gather(*tasks)

    # 等待所有投递完成
    await asyncio.sleep(0.5)

    elapsed = time.time() - start_time
    throughput = events / elapsed if elapsed > 0 else 0

    # 内存使用
    usage = resource.getrusage(resource.RUSAGE_SELF)
    if sys.platform == "darwin":
        max_rss_mb = usage.ru_maxrss / (1024 * 1024)
    else:
        max_rss_mb = usage.ru_maxrss / 1024

    await engine.stop()

    result = {
        "events_sent": events,
        "alerts_received": len(alerts_received),
        "concurrency": concurrency,
        "elapsed_sec": round(elapsed, 3),
        "throughput_eps": round(throughput, 2),
        "max_rss_mb": round(max_rss_mb, 2),
        "eventbus_subscriber_count": bus.subscriber_count,
    }

    if output:
        _out_path = Path(output)
        _out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"结果已写入 {_out_path}")

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="NewsSentry 实时引擎压测")
    parser.add_argument(
        "--events", type=int, default=1000, help="事件数 (默认 1000)"
    )
    parser.add_argument(
        "--concurrency", type=int, default=10, help="并发数 (默认 10)"
    )
    parser.add_argument(
        "--output", type=str, default=None, help="输出 JSON 文件路径"
    )
    args = parser.parse_args()

    print(f"压测参数: events={args.events}, concurrency={args.concurrency}")
    print("-" * 50)

    result = asyncio.run(_run_stress(args.events, args.concurrency, args.output))

    print(f"发送事件:   {result['events_sent']}")
    print(f"接收告警:   {result['alerts_received']}")
    print(f"耗时:       {result['elapsed_sec']}s")
    print(f"吞吐量:     {result['throughput_eps']} events/s")
    print(f"最大 RSS:   {result['max_rss_mb']} MB")
    print(f"订阅者数:   {result['eventbus_subscriber_count']}")

    # 成功判断
    if result["alerts_received"] >= result["events_sent"] * 0.95:
        print("\n[PASS] 告警投递率 >= 95%")
    else:
        rate = result["alerts_received"] / max(result["events_sent"], 1) * 100
        print(f"\n[WARN] 告警投递率 = {rate:.1f}%")


if __name__ == "__main__":
    main()
