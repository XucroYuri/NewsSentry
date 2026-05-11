"""APICollector 模块测试。

覆盖：正常采集、字段映射、错误处理、沙箱拦截、空数据、语言检测等。
"""
from __future__ import annotations

from unittest import mock

import pytest

from news_sentry.models.newsevent import Language, NewsEvent, PipelineStage
from news_sentry.skills.collect.api_collector import APICollector

# ── 测试用 fixture / helper ────────────────────────────────────────


def _make_minimal_config(**overrides) -> dict:
    """生成最小 API SourceChannel 配置。"""
    data: dict = {
        "target_id": "test-target",
        "source_id": "test-api-source",
        "display_name": "Test API Source",
        "type": "api",
        "url": "https://example.com/api/news",
        "credibility_base": 0.8,
        "fetch_interval_minutes": 15,
        "max_items_per_run": 50,
        "timeout_seconds": 30,
        "enabled": True,
        "health": {"last_success_at": None, "consecutive_failures": 0},
    }
    data.update(overrides)
    return data


def _make_mock_response(json_data: object, status_code: int = 200) -> mock.MagicMock:
    """构造 httpx.get 的 mock 返回值。"""
    resp = mock.MagicMock()
    resp.json.return_value = json_data
    resp.status_code = status_code
    resp.raise_for_status = mock.MagicMock()
    return resp


def _make_mock_api_item(
    title: str = "Test Title",
    url: str = "https://example.com/item/1",
    content: str = "Test content.",
    published_at: str = "2026-05-10T10:30:00+00:00",
    **extra,
) -> dict:
    """构造单个 API 返回条目。"""
    item: dict = {
        "title": title,
        "url": url,
        "content": content,
        "published_at": published_at,
        "id": f"item-{url.split('/')[-1]}",
    }
    item.update(extra)
    return item


def _make_api_response(items: list[dict]) -> dict:
    """构造典型的 API 响应 (JSON 对象含 items 数组)。"""
    return {"items": items, "total": len(items)}


# ── APICollector.__init__ ──────────────────────────────────────────


class TestInit:
    def test_stores_config_and_sandbox(self):
        config = _make_minimal_config()
        sandbox = object()
        collector = APICollector(config, sandbox)
        assert collector._config is config
        assert collector._sandbox is sandbox

    def test_extracts_fields_from_config(self):
        config = _make_minimal_config(
            source_id="ansa-api",
            url="https://ansa.it/api/news",
            timeout_seconds=15,
            max_items_per_run=25,
        )
        collector = APICollector(config, None)
        assert collector._source_id == "ansa-api"
        assert collector._url == "https://ansa.it/api/news"
        assert collector._timeout == 15.0
        assert collector._max_items == 25

    def test_defaults_for_missing_optional_fields(self):
        config = _make_minimal_config()
        del config["timeout_seconds"]
        del config["max_items_per_run"]
        collector = APICollector(config, None)
        assert collector._timeout == 30.0
        assert collector._max_items == 50

    def test_missing_url_defaults_to_empty(self):
        config = _make_minimal_config()
        del config["url"]
        collector = APICollector(config, None)
        assert collector._url == ""

    def test_api_mapping_defaults_to_empty_dict(self):
        config = _make_minimal_config()
        collector = APICollector(config, None)
        assert collector._mapping == {}

    def test_api_mapping_is_stored(self):
        config = _make_minimal_config(
            api_mapping={"title": "headline", "url": "link", "items_key": "articles"},
        )
        collector = APICollector(config, None)
        assert collector._mapping["title"] == "headline"
        assert collector._mapping["url"] == "link"
        assert collector._mapping["items_key"] == "articles"


# ── APICollector.collect ───────────────────────────────────────────


class TestCollect:
    def test_collect_returns_events_from_json_api(self):
        """正常 JSON API 响应应返回 NewsEvent 列表。"""
        config = _make_minimal_config(source_id="test-api")
        collector = APICollector(config, None)

        items = [
            _make_mock_api_item(title="News 1", url="https://x.com/1"),
            _make_mock_api_item(title="News 2", url="https://x.com/2"),
        ]
        mock_resp = _make_mock_response(_make_api_response(items))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-abc")

        assert len(result) == 2
        assert isinstance(result[0], NewsEvent)
        assert result[0].pipeline_stage == PipelineStage.COLLECTED
        assert result[0].source_id == "test-api"
        assert result[0].run_id == "run-abc"
        assert result[0].title_original == "News 1"
        assert result[0].url == "https://x.com/1"
        assert result[0].content_original == "Test content."

    def test_collect_uses_api_mapping_for_field_names(self):
        """验证 api_mapping 自定义字段名生效。"""
        config = _make_minimal_config(
            source_id="custom-api",
            api_mapping={
                "title": "headline",
                "url": "permalink",
                "content": "body",
                "published_at": "created_at",
                "items_key": "results",
            },
        )
        collector = APICollector(config, None)

        item = {
            "headline": "Custom Mapped Title",
            "permalink": "https://custom.example.com/1",
            "body": "Full body text from custom API.",
            "created_at": "2026-05-09T08:00:00+00:00",
            "id": "custom-1",
        }
        mock_resp = _make_mock_response({"results": [item]})

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        event = result[0]
        assert event.title_original == "Custom Mapped Title"
        assert event.url == "https://custom.example.com/1"
        assert event.content_original == "Full body text from custom API."

    def test_collect_returns_empty_on_empty_url(self):
        """空 URL 返回空列表。"""
        config = _make_minimal_config(url="")
        collector = APICollector(config, None)
        result = collector.collect("run-001")
        assert result == []

    def test_collect_returns_empty_on_none_url(self):
        """url 为 None 时返回空列表。"""
        config = _make_minimal_config(url=None)
        collector = APICollector(config, None)
        result = collector.collect("run-001")
        assert result == []

    def test_collect_raises_on_http_error(self):
        """HTTP 网络错误应抛 RuntimeError。"""
        config = _make_minimal_config(url="https://error.example.com/api")
        collector = APICollector(config, None)

        with mock.patch("httpx.get", side_effect=Exception("Connection refused")):
            with pytest.raises(RuntimeError, match="API fetch failed"):
                collector.collect("run-001")

    def test_collect_raises_on_http_status_error(self):
        """HTTP 状态码错误（如 404）应抛 RuntimeError。"""
        config = _make_minimal_config(url="https://example.com/404")
        collector = APICollector(config, None)

        mock_resp = _make_mock_response({}, status_code=404)
        mock_resp.raise_for_status.side_effect = Exception("HTTP 404")

        with mock.patch("httpx.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="API fetch failed"):
                collector.collect("run-001")

    def test_collect_raises_on_non_dict_response(self):
        """JSON 响应为数组（非对象）应抛 RuntimeError。"""
        config = _make_minimal_config(url="https://example.com/api")
        collector = APICollector(config, None)

        mock_resp = _make_mock_response([{"title": "Item 1"}, {"title": "Item 2"}])

        with mock.patch("httpx.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="not a JSON object"):
                collector.collect("run-001")

    def test_collect_raises_on_items_not_list(self):
        """items 字段不是列表时应抛 RuntimeError。"""
        config = _make_minimal_config(url="https://example.com/api")
        collector = APICollector(config, None)

        mock_resp = _make_mock_response({"items": "not-a-list"})

        with mock.patch("httpx.get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="items field is not a list"):
                collector.collect("run-001")

    def test_collect_respects_max_items(self):
        """验证 max_items_per_run 截断。"""
        config = _make_minimal_config(max_items_per_run=3)
        collector = APICollector(config, None)

        items = [
            _make_mock_api_item(title=f"Item {i}", url=f"https://example.com/item/{i}")
            for i in range(10)
        ]
        mock_resp = _make_mock_response(_make_api_response(items))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 3

    def test_collect_sandbox_block_returns_empty(self):
        """沙箱策略拒绝时应返回空列表。"""
        config = _make_minimal_config(url="https://blocked.example.com/api")
        sandbox = mock.MagicMock()
        sandbox.check_network_host.return_value = False
        collector = APICollector(config, sandbox)

        result = collector.collect("run-001")

        assert result == []
        sandbox.check_network_host.assert_called_once_with("blocked.example.com")

    def test_collect_sandbox_allow_proceeds(self):
        """沙箱策略允许时应继续正常采集。"""
        config = _make_minimal_config(url="https://allowed.example.com/api")
        sandbox = mock.MagicMock()
        sandbox.check_network_host.return_value = True
        collector = APICollector(config, sandbox)

        items = [_make_mock_api_item(title="Allowed", url="https://allowed.example.com/1")]
        mock_resp = _make_mock_response(_make_api_response(items))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].title_original == "Allowed"
        sandbox.check_network_host.assert_called_once_with("allowed.example.com")

    def test_collect_handles_missing_fields(self):
        """条目缺少 title/url 时生成含空字符串的事件。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        items = [{"id": "minimal-1"}]  # 无 title, url, content
        mock_resp = _make_mock_response(_make_api_response(items))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        event = result[0]
        assert event.title_original == ""
        assert event.url == ""
        assert event.content_original == ""
        assert isinstance(event, NewsEvent)

    def test_collect_uses_data_field_as_items(self):
        """当没有 items 键时，应使用 data 字段。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        items = [
            _make_mock_api_item(title="From data", url="https://x.com/data/1"),
        ]
        mock_resp = _make_mock_response({"data": items})

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].title_original == "From data"

    def test_collect_uses_articles_field_as_items(self):
        """当没有 items 和 data 键时，应使用 articles 字段。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        items = [
            _make_mock_api_item(title="From articles", url="https://x.com/articles/1"),
        ]
        mock_resp = _make_mock_response({"articles": items})

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].title_original == "From articles"

    def test_collect_uses_items_key_from_api_mapping(self):
        """api_mapping 中的 items_key 指定列表键名时应优先使用。"""
        config = _make_minimal_config(
            api_mapping={"items_key": "records"},
        )
        collector = APICollector(config, None)

        # 构造同时有 records、data、items 的响应，应优先用 records
        items = [_make_mock_api_item(title="From records", url="https://x.com/records/1")]
        mock_resp = _make_mock_response({
            "items": [],
            "data": [],
            "records": items,
        })

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].title_original == "From records"

    def test_item_to_event_language_detection(self):
        """验证从字段自动检测语言。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        # 意大利语
        item_it = _make_mock_api_item(
            title="Notizia",
            url="https://ansa.it/1",
            language="it",
        )
        event_it = collector._item_to_event(item_it, "run-001")
        assert event_it.language == Language.IT

        # 英语
        item_en = _make_mock_api_item(
            title="News",
            url="https://bbc.com/1",
            language="en",
        )
        event_en = collector._item_to_event(item_en, "run-001")
        assert event_en.language == Language.EN

        # 中文
        item_zh = _make_mock_api_item(
            title="新闻",
            url="https://xinhua.cn/1",
            language="zh",
        )
        event_zh = collector._item_to_event(item_zh, "run-001")
        assert event_zh.language == Language.ZH

        # 未知语言 → MIXED
        item_unknown = _make_mock_api_item(
            title="Notizie",
            url="https://example.com/1",
            language="fr",
        )
        event_unknown = collector._item_to_event(item_unknown, "run-001")
        assert event_unknown.language == Language.MIXED

    def test_item_to_event_language_detection_via_lang_field(self):
        """验证通过 lang 字段检测语言（无 language 字段）。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        # 仅提供 lang 字段（无 language 字段），验证 fallback
        item = _make_mock_api_item(
            title="News",
            url="https://example.com/1",
            lang="en-US",
        )
        # item 中不含 "language" 键，测试 lang fallback
        assert "language" not in item
        event = collector._item_to_event(item, "run-001")
        assert event.language == Language.EN

    def test_item_to_event_language_mixed_when_no_lang_fields(self):
        """无语言字段时默认为 MIXED。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        item = {
            "title": "Some Title",
            "url": "https://example.com/1",
            "id": "no-lang",
        }
        event = collector._item_to_event(item, "run-001")
        assert event.language == Language.MIXED

    def test_item_to_event_language_via_api_mapping(self):
        """通过 api_mapping 指定语言字段名。"""
        config = _make_minimal_config(
            api_mapping={"language": "locale"},
        )
        collector = APICollector(config, None)

        item = {
            "title": "Notizia",
            "url": "https://example.com/1",
            "locale": "it-IT",
            "id": "lang-1",
        }
        event = collector._item_to_event(item, "run-001")
        assert event.language == Language.IT

    def test_collect_skips_non_dict_items(self):
        """列表中非 dict 类型的条目应被跳过。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        good_item = _make_mock_api_item(title="Good", url="https://x.com/good")
        items = ["not-a-dict", 123, None, good_item]
        mock_resp = _make_mock_response(_make_api_response(items))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].title_original == "Good"

    def test_collect_skips_broken_items(self):
        """字段转换异常时跳过该条目继续处理后续条目。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        items = [
            _make_mock_api_item(title="Good 1", url="https://x.com/good1"),
            _make_mock_api_item(title="Good 2", url="https://x.com/good2"),
        ]
        mock_resp = _make_mock_response(_make_api_response(items))

        # 让 _item_to_event 对第一个条目抛异常
        original = collector._item_to_event
        call_count = [0]

        def side_effect(item, run_id):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("模拟条目构建失败")
            return original(item, run_id)

        with mock.patch.object(collector, "_item_to_event", side_effect=side_effect):
            with mock.patch("httpx.get", return_value=mock_resp):
                result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].title_original == "Good 2"

    def test_collect_empty_items_list_returns_empty(self):
        """API 响应 items 为空列表时返回空列表。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        mock_resp = _make_mock_response({"items": []})

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert result == []

    def test_collect_uses_link_field_as_url_fallback(self):
        """当条目没有 url 字段但有 link 字段时，使用 link。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        item = {
            "title": "Link Fallback",
            "link": "https://example.com/linked",
            "content": "Using link field.",
            "published_at": "2026-05-10T10:00:00+00:00",
            "id": "link-1",
        }
        mock_resp = _make_mock_response(_make_api_response([item]))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert len(result) == 1
        assert result[0].url == "https://example.com/linked"

    def test_collect_uses_summary_field_as_content_fallback(self):
        """当条目没有 content 但有 summary 时，使用 summary。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        item = {
            "title": "Summary Fallback",
            "url": "https://example.com/summary",
            "summary": "Short summary text.",
            "published_at": "2026-05-10T10:00:00+00:00",
            "id": "summary-1",
        }
        mock_resp = _make_mock_response(_make_api_response([item]))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert result[0].content_original == "Short summary text."

    def test_collect_uses_description_field_as_content_fallback(self):
        """当没有 content/summary 但有 description 时，使用 description。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        item = {
            "title": "Description Fallback",
            "url": "https://example.com/desc",
            "description": "Description text.",
            "published_at": "2026-05-10T10:00:00+00:00",
            "id": "desc-1",
        }
        mock_resp = _make_mock_response(_make_api_response([item]))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert result[0].content_original == "Description text."

    def test_collect_uses_date_field_as_published_at_fallback(self):
        """当条目没有 published_at 但有 date 时，使用 date。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        item = {
            "title": "Date Fallback",
            "url": "https://example.com/date",
            "content": "Content here.",
            "date": "2026-05-09T15:00:00+00:00",
            "id": "date-1",
        }
        mock_resp = _make_mock_response(_make_api_response([item]))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert "2026-05-09" in result[0].published_at

    def test_collect_published_at_missing_falls_back_to_now(self):
        """所有日期均缺失时，published_at 应为当前时间。"""
        config = _make_minimal_config()
        collector = APICollector(config, None)

        item = {
            "title": "No Date",
            "url": "https://example.com/nodate",
            "content": "Content.",
            "id": "nodate-1",
        }
        mock_resp = _make_mock_response(_make_api_response([item]))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        assert "T" in result[0].published_at
        assert isinstance(result[0].published_at, str)

    def test_collect_metadata_is_set_correctly(self):
        """验证 metadata 各字段正确。"""
        config = _make_minimal_config(
            source_id="meta-source",
            url="https://meta.example.com/api/v1/news",
        )
        collector = APICollector(config, None)

        item = _make_mock_api_item(
            title="Metadata Test",
            url="https://meta.example.com/1",
            published_at="2026-05-10T10:30:00+00:00",
        )
        mock_resp = _make_mock_response(_make_api_response([item]))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-meta")

        meta = result[0].metadata
        assert "collection" in meta
        assert meta["collection"]["method"] == "api"
        assert meta["collection"]["api_url"] == "https://meta.example.com/api/v1/news"
        assert meta["collection"]["raw_item_id"] == "item-1"

    def test_collect_id_format(self):
        """验证生成的 event id 格式。"""
        config = _make_minimal_config(
            target_id="italy",
            source_id="ansaapi",
        )
        collector = APICollector(config, None)

        item = _make_mock_api_item(
            title="ID Test",
            url="https://ansa.it/api/article/1",
            published_at="2026-05-10T10:30:00+00:00",
        )
        mock_resp = _make_mock_response(_make_api_response([item]))

        with mock.patch("httpx.get", return_value=mock_resp):
            result = collector.collect("run-001")

        event_id = result[0].id
        parts = event_id.split("-")
        assert parts[0] == "ne"
        assert parts[1] == "italy"
        assert parts[2] == "ansaapi"
        assert parts[3] == "20260510"
        assert len(parts[4]) == 8


# ── _retry_fetch 重试逻辑 ─────────────────────────────────────────


class TestRetryFetch:
    """_retry_fetch 函数重试逻辑测试。"""

    def test_4xx_not_retried(self):
        """4xx HTTP 错误不应重试，直接抛出。"""
        import httpx

        from news_sentry.skills.collect.api_collector import _retry_fetch

        mock_resp = mock.MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=mock.MagicMock(), response=mock.MagicMock(status_code=404)
        )
        mock_resp.response = mock.MagicMock(status_code=404)

        call_count = 0

        def fetch_fn():
            nonlocal call_count
            call_count += 1
            return mock_resp

        with pytest.raises(httpx.HTTPStatusError):
            _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert call_count == 1  # 不重试

    def test_retries_exhausted_raises_runtime_error(self):
        """重试耗尽后抛出 RuntimeError。"""
        import httpx

        from news_sentry.skills.collect.api_collector import _retry_fetch

        mock_resp = mock.MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=mock.MagicMock(), response=mock.MagicMock(status_code=500)
        )
        mock_resp.response = mock.MagicMock(status_code=500)

        with mock.patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Fetch failed"):
                _retry_fetch(
                    lambda: mock_resp,
                    "test-source",
                    max_retries=2,
                )

    def test_runtime_error_reraised(self):
        """fetch 抛出的 RuntimeError 应直接向上传递（不包装）。"""
        from news_sentry.skills.collect.api_collector import _retry_fetch

        def fetch_fn():
            raise RuntimeError("already wrapped")

        with pytest.raises(RuntimeError, match="already wrapped"):
            _retry_fetch(fetch_fn, "test-source", max_retries=0)
