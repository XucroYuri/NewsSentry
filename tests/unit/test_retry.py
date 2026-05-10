"""Retry/Backoff 模块测试。

覆盖：_retry_fetch 指数退避、4xx 不重试、5xx 重试、网络错误重试、
首次失败第二次成功。
从 rss_collector 导入 _retry_fetch（两个 collector 中代码相同）。
"""
from __future__ import annotations

from unittest import mock

import httpx
import pytest

from news_sentry.skills.collect.rss_collector import _retry_fetch

# ── 辅助 ────────────────────────────────────────────────────────────────

def _make_mock_response(status_code: int = 200) -> mock.MagicMock:
    """构造 httpx.Response 的 mock。"""
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = mock.MagicMock()
    return resp


# ── 重试逻辑 ────────────────────────────────────────────────────────────

class TestRetryOnConnectionError:
    """网络错误时的重试行为。"""

    def test_retry_on_connection_error(self):
        """mock httpx.ConnectError，验证 3 次重试后抛 RuntimeError。"""
        fetch_fn = mock.MagicMock(side_effect=httpx.ConnectError("Connection refused"))

        with mock.patch("time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError, match="Fetch failed for test-source"):
                _retry_fetch(fetch_fn, "test-source", max_retries=3)

        # 初始调用 + 3 次重试 = 4 次调用
        assert fetch_fn.call_count == 4
        # 验证指数退避: 1s, 2s, 4s
        assert mock_sleep.call_count == 3
        assert mock_sleep.call_args_list[0].args[0] == 1
        assert mock_sleep.call_args_list[1].args[0] == 2
        assert mock_sleep.call_args_list[2].args[0] == 4

    def test_retry_on_timeout(self):
        """mock httpx.TimeoutException，验证重试后抛 RuntimeError。"""
        fetch_fn = mock.MagicMock(side_effect=httpx.TimeoutException("Read timed out"))

        with mock.patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Fetch failed for test-source"):
                _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert fetch_fn.call_count == 4

    def test_retry_on_os_error(self):
        """mock OSError，验证重试后抛 RuntimeError。"""
        fetch_fn = mock.MagicMock(side_effect=OSError("Network is unreachable"))

        with mock.patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Fetch failed for test-source"):
                _retry_fetch(fetch_fn, "test-source", max_retries=2)

        assert fetch_fn.call_count == 3  # 初始 + 2 次重试

    def test_retry_on_connection_error_stdlib(self):
        """mock 标准库 ConnectionError，验证重试。"""
        fetch_fn = mock.MagicMock(side_effect=ConnectionError("Refused"))

        with mock.patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Fetch failed for test-source"):
                _retry_fetch(fetch_fn, "test-source", max_retries=1)

        assert fetch_fn.call_count == 2

    def test_retry_on_timeout_error_stdlib(self):
        """mock 标准库 TimeoutError，验证重试。"""
        fetch_fn = mock.MagicMock(side_effect=TimeoutError("Timed out"))

        with mock.patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Fetch failed for test-source"):
                _retry_fetch(fetch_fn, "test-source", max_retries=1)

        assert fetch_fn.call_count == 2


class TestNoRetryOn4xx:
    """4xx 客户端错误不重试。"""

    def test_no_retry_on_404(self):
        """HTTP 404 直接抛异常，不重试。"""
        mock_resp = _make_mock_response(status_code=404)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=mock.MagicMock(), response=mock_resp
        )
        fetch_fn = mock.MagicMock(return_value=mock_resp)

        with mock.patch("time.sleep") as mock_sleep:
            with pytest.raises(httpx.HTTPStatusError):
                _retry_fetch(fetch_fn, "test-source", max_retries=3)

        # 只调用一次，没有重试
        assert fetch_fn.call_count == 1
        mock_sleep.assert_not_called()

    def test_no_retry_on_400(self):
        """HTTP 400 直接抛异常，不重试。"""
        mock_resp = _make_mock_response(status_code=400)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Bad Request", request=mock.MagicMock(), response=mock_resp
        )
        fetch_fn = mock.MagicMock(return_value=mock_resp)

        with mock.patch("time.sleep") as mock_sleep:
            with pytest.raises(httpx.HTTPStatusError):
                _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert fetch_fn.call_count == 1
        mock_sleep.assert_not_called()

    def test_no_retry_on_403(self):
        """HTTP 403 直接抛异常，不重试。"""
        mock_resp = _make_mock_response(status_code=403)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=mock.MagicMock(), response=mock_resp
        )
        fetch_fn = mock.MagicMock(return_value=mock_resp)

        with mock.patch("time.sleep") as mock_sleep:
            with pytest.raises(httpx.HTTPStatusError):
                _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert fetch_fn.call_count == 1
        mock_sleep.assert_not_called()


class TestRetryOn5xx:
    """5xx 服务端错误进行重试。"""

    def test_retry_on_503(self):
        """HTTP 503 触发重试。"""
        mock_resp = _make_mock_response(status_code=503)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=mock.MagicMock(), response=mock_resp
        )
        fetch_fn = mock.MagicMock(return_value=mock_resp)

        with mock.patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Fetch failed for test-source"):
                _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert fetch_fn.call_count == 4

    def test_retry_on_500(self):
        """HTTP 500 触发重试。"""
        mock_resp = _make_mock_response(status_code=500)
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Internal Server Error", request=mock.MagicMock(), response=mock_resp
        )
        fetch_fn = mock.MagicMock(return_value=mock_resp)

        with mock.patch("time.sleep"):
            with pytest.raises(RuntimeError, match="Fetch failed for test-source"):
                _retry_fetch(fetch_fn, "test-source", max_retries=2)

        assert fetch_fn.call_count == 3


class TestSuccessOnRetry:
    """重试后成功的情况。"""

    def test_success_on_second_try(self):
        """第一次调用失败（5xx），第二次成功，验证返回正确结果。"""
        fail_resp = _make_mock_response(status_code=503)
        fail_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=mock.MagicMock(), response=fail_resp
        )

        success_resp = _make_mock_response(status_code=200)
        success_resp.text = "ok"

        fetch_fn = mock.MagicMock(side_effect=[fail_resp, success_resp])

        with mock.patch("time.sleep") as mock_sleep:
            result = _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert fetch_fn.call_count == 2
        assert result is success_resp
        # 第一次重试前 sleep 了 1 秒
        mock_sleep.assert_called_once_with(1)

    def test_success_on_third_try(self):
        """前两次失败，第三次成功。"""
        fail_1 = _make_mock_response(status_code=503)
        fail_1.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=mock.MagicMock(), response=fail_1
        )
        fail_2 = _make_mock_response(status_code=503)
        fail_2.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=mock.MagicMock(), response=fail_2
        )
        success_resp = _make_mock_response(status_code=200)

        fetch_fn = mock.MagicMock(side_effect=[fail_1, fail_2, success_resp])

        with mock.patch("time.sleep") as mock_sleep:
            result = _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert fetch_fn.call_count == 3
        assert result is success_resp
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0].args[0] == 1
        assert mock_sleep.call_args_list[1].args[0] == 2

    def test_first_try_success(self):
        """第一次调用就成功，无重试无 sleep。"""
        success_resp = _make_mock_response(status_code=200)
        fetch_fn = mock.MagicMock(return_value=success_resp)

        with mock.patch("time.sleep") as mock_sleep:
            result = _retry_fetch(fetch_fn, "test-source", max_retries=3)

        assert fetch_fn.call_count == 1
        assert result is success_resp
        mock_sleep.assert_not_called()

    def test_zero_retries_raises_on_first_failure(self):
        """max_retries=0 时首次失败直接抛异常。"""
        fetch_fn = mock.MagicMock(side_effect=httpx.ConnectError("fail"))

        with mock.patch("time.sleep") as mock_sleep:
            with pytest.raises(RuntimeError, match="Fetch failed for src"):
                _retry_fetch(fetch_fn, "src", max_retries=0)

        assert fetch_fn.call_count == 1
        mock_sleep.assert_not_called()
