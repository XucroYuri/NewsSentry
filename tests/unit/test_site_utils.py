"""site_utils 单元测试 — SEO 注入、页面文案、安全头等。"""

from news_sentry.core._state import (
    _PUBLIC_SITE_DESCRIPTION,
    _PUBLIC_SITE_DESCRIPTION_IT,
    _PUBLIC_SITE_TITLE,
    _PUBLIC_SITE_TITLE_IT,
)
from news_sentry.core.site_utils import (
    _inject_inline_css,
    _inject_public_homepage_seo,
    _inject_script_nonce,
    _public_app_page_copy,
)

# ── 基础 HTML 模板（模拟前端 build 产物） ──
_BASE_HTML = """\
<!doctype html>
<html>
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>News Sentry</title>
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>"""

# ═══════════════════════════════════════════════
# _public_app_page_copy
# ═══════════════════════════════════════════════


def test_page_copy_chinese_root():
    """中文首页返回中文标题和描述。"""
    title, desc = _public_app_page_copy("/public-app/", "zh")
    assert title == _PUBLIC_SITE_TITLE
    assert desc == _PUBLIC_SITE_DESCRIPTION


def test_page_copy_italian_root():
    """意大利语首页返回意大利语标题和描述。"""
    title, desc = _public_app_page_copy("/public-app/", "it")
    assert title == _PUBLIC_SITE_TITLE_IT
    assert desc == _PUBLIC_SITE_DESCRIPTION_IT


def test_page_copy_sources_zh():
    title, desc = _public_app_page_copy("/sources", "zh")
    assert "来源" in title
    assert "信源" in desc


def test_page_copy_sources_it():
    title, desc = _public_app_page_copy("/sources", "it")
    assert "Fonti" in title
    assert "fonti giornalistiche" in desc


def test_page_copy_subscribe_zh():
    title, desc = _public_app_page_copy("/subscribe", "zh")
    assert "订阅" in title
    assert "每日信号" in desc


def test_page_copy_subscribe_it():
    title, desc = _public_app_page_copy("/subscribe", "it")
    assert "Iscriviti" in title
    assert "Ricevi" in desc


# ═══════════════════════════════════════════════
# _inject_public_homepage_seo
# ═══════════════════════════════════════════════


def test_inject_seo_sets_html_lang_zh():
    """中文 locale 设置 html lang="zh-CN"。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    assert 'lang="zh-CN"' in result


def test_inject_seo_sets_html_lang_it():
    """意大利语 locale 设置 html lang="it"。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="it"
    )
    assert 'lang="it"' in result


def test_inject_seo_adds_meta_description_zh():
    """中文首页注入中文 meta description。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    assert f'<meta name="description" content="{_PUBLIC_SITE_DESCRIPTION}" />' in result


def test_inject_seo_adds_meta_description_it():
    """意大利语首页注入意大利语 meta description。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="it"
    )
    assert f'<meta name="description" content="{_PUBLIC_SITE_DESCRIPTION_IT}" />' in result


def test_inject_seo_adds_canonical():
    """注入 canonical link。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    assert '<link rel="canonical" href="https://news-sentry.com/public-app/" />' in result


def test_inject_seo_adds_canonical_sub_path():
    """子页面 canonical 带正确路径。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML,
        base_url="https://news-sentry.com",
        canonical_path="/sources",
        locale="zh",
    )
    assert '<link rel="canonical" href="https://news-sentry.com/sources" />' in result


def test_inject_seo_adds_hreflang():
    """注入 3 条 hreflang alternate 链接。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    assert 'hreflang="zh-CN"' in result
    assert 'hreflang="it"' in result
    assert 'hreflang="x-default"' in result


def test_inject_seo_adds_og_tags_zh():
    """中文首页注入 zh_CN Open Graph 标签。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    assert f'<meta property="og:title" content="{_PUBLIC_SITE_TITLE}" />' in result
    assert f'<meta property="og:description" content="{_PUBLIC_SITE_DESCRIPTION}" />' in result
    assert '<meta property="og:url" content="https://news-sentry.com/public-app/" />' in result
    assert '<meta property="og:locale" content="zh_CN" />' in result
    assert '<meta property="og:locale:alternate" content="it_IT" />' in result


def test_inject_seo_adds_og_tags_it():
    """意大利语首页注入 it_IT Open Graph 标签（alternate 是 zh_CN）。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="it"
    )
    assert '<meta property="og:locale" content="it_IT" />' in result
    assert '<meta property="og:locale:alternate" content="zh_CN" />' in result


def test_inject_seo_adds_og_image():
    """注入 og:image 系列标签。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    og_image = '<meta property="og:image" content="https://news-sentry.com/icons/icon-192.svg" />'
    assert og_image in result
    assert '<meta property="og:image:alt" content="News Sentry logo" />' in result
    assert '<meta property="og:image:width" content="192" />' in result
    assert '<meta property="og:image:height" content="192" />' in result


def test_inject_seo_adds_twitter_card_zh():
    """中文首页注入 Twitter Card 标签。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    assert '<meta name="twitter:card" content="summary" />' in result
    assert f'<meta name="twitter:title" content="{_PUBLIC_SITE_TITLE}" />' in result
    assert f'<meta name="twitter:description" content="{_PUBLIC_SITE_DESCRIPTION}" />' in result
    assert (
        '<meta name="twitter:image" content="https://news-sentry.com/icons/icon-192.svg" />'
        in result
    )


def test_inject_seo_adds_twitter_card_it():
    """意大利语首页注入 Twitter Card 标签（意大利语文案）。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="it"
    )
    assert '<meta name="twitter:card" content="summary" />' in result
    assert f'<meta name="twitter:title" content="{_PUBLIC_SITE_TITLE_IT}" />' in result
    assert f'<meta name="twitter:description" content="{_PUBLIC_SITE_DESCRIPTION_IT}" />' in result


def test_inject_seo_adds_json_ld():
    """注入 JSON-LD 结构化数据。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    assert '<script type="application/ld+json">' in result
    assert '"@type": "CollectionPage"' in result
    assert '"inLanguage": "zh-CN"' in result
    assert '"News Sentry"' in result


def test_inject_seo_json_ld_it_language():
    """意大利语页面的 JSON-LD inLanguage 是 it。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="it"
    )
    assert '"inLanguage": "it"' in result


def test_inject_seo_idempotent():
    """重复注入不产生重复标签。"""
    first = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    second = _inject_public_homepage_seo(
        first, base_url="https://news-sentry.com", locale="zh"
    )
    assert first.count('name="description"') == 1
    assert first == second


def test_inject_seo_idempotent_after_locale_switch():
    """
    如果 HTML 已经被某种语言注入了 SEO 标签，再以另一种语言调用时不重复注入。
    这是设计行为：SEO 注入以"是否存在标签"为守卫，不是以 locale 为守卫。
    """
    zh_result = _inject_public_homepage_seo(
        _BASE_HTML, base_url="https://news-sentry.com", locale="zh"
    )
    # 再次以 it 调用已被 zh 注入过的 HTML——不应追加额外标签
    it_result = _inject_public_homepage_seo(
        zh_result, base_url="https://news-sentry.com", locale="it"
    )
    # hreflang 守卫检查 zh-CN 是否存在，所以不会重复
    assert zh_result.count('hreflang="zh-CN"') == 1
    assert it_result.count('hreflang="zh-CN"') == 1


def test_inject_seo_sub_page_sources():
    """子页面 /sources 注入正确文案。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML,
        base_url="https://news-sentry.com",
        canonical_path="/sources",
        locale="zh",
    )
    assert 'content="来源目录"' in result
    assert "信源" in result
    assert "canonical" in result


def test_inject_seo_sub_page_subscribe_it():
    """子页面 /subscribe 意大利语。"""
    result = _inject_public_homepage_seo(
        _BASE_HTML,
        base_url="https://news-sentry.com",
        canonical_path="/subscribe",
        locale="it",
    )
    assert 'content="Iscriviti"' in result
    assert "Ricevi" in result


# ═══════════════════════════════════════════════
# _inject_script_nonce
# ═══════════════════════════════════════════════


def test_inject_nonce_adds_attribute():
    html = '<script src="/main.js"></script>'
    result = _inject_script_nonce(html, "abc123nonce")
    assert 'nonce="abc123nonce"' in result


def test_inject_nonce_skips_existing():
    html = '<script nonce="old" src="/main.js"></script>'
    result = _inject_script_nonce(html, "new")
    assert 'nonce="old"' in result
    assert 'nonce="new"' not in result


def test_inject_nonce_multiple_tags():
    html = '<script src="/a.js"></script>\n<script src="/b.js"></script>'
    result = _inject_script_nonce(html, "n")
    assert result.count('nonce="n"') == 2


# ═══════════════════════════════════════════════
# _inject_inline_css (边缘情况)
# ═══════════════════════════════════════════════


def test_inject_inline_css_handles_no_head_tag():
    """当 HTML 无 </head> 时，内联 CSS 被注入到 HTML 之前（不崩溃）。"""
    result = _inject_inline_css("<html><body></body></html>", "nonce123")
    # CSS 被注入到 HTML 前面（因为没找到 </head>）
    assert "nonce123" in result
    assert result.startswith("\n<style")
