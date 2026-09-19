from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_vercel_geist_vendor_docs_are_recorded() -> None:
    vendor_dir = REPO_ROOT / "docs" / "design" / "vendor" / "vercel"
    light = vendor_dir / "design.md"
    dark = vendor_dir / "design.dark.md"
    receipt = vendor_dir / "README.md"

    assert light.exists()
    assert dark.exists()
    assert receipt.exists()
    assert "name: Geist" in light.read_text()
    assert "name: Geist" in dark.read_text()

    receipt_text = receipt.read_text()
    assert "https://vercel.com/design.md" in receipt_text
    assert "https://vercel.com/design.dark.md" in receipt_text
    assert "sha256" in receipt_text


def test_shared_geist_design_system_is_wired_to_both_frontends() -> None:
    token_css = REPO_ROOT / "frontend" / "design-system" / "geist-tokens.css"
    preset = REPO_ROOT / "frontend" / "design-system" / "tailwind-geist-preset.ts"
    public_tailwind = REPO_ROOT / "frontend" / "public" / "tailwind.config.ts"
    admin_tailwind = REPO_ROOT / "frontend" / "admin" / "tailwind.config.ts"
    public_css = REPO_ROOT / "frontend" / "public" / "src" / "index.css"
    admin_css = REPO_ROOT / "frontend" / "admin" / "src" / "index.css"

    token_text = token_css.read_text()
    assert "@font-face" in token_text
    assert "Geist-Variable.woff2" in token_text
    assert "GeistMono-Variable.woff2" in token_text
    assert "--geist-gray-1000: 23 23 23" in token_text
    assert "--geist-gray-1000: 237 237 237" in token_text
    assert "@media (prefers-color-scheme: dark)" in token_text
    assert ":root.dark" in token_text
    assert (REPO_ROOT / "frontend" / "design-system" / "fonts" / "Geist-Variable.woff2").exists()
    assert (
        REPO_ROOT / "frontend" / "design-system" / "fonts" / "GeistMono-Variable.woff2"
    ).exists()

    preset_text = preset.read_text()
    assert 'background: rgbVar("--background")' in preset_text
    assert "boxShadow" in preset_text

    assert "geistPreset" in public_tailwind.read_text()
    assert "geistPreset" in admin_tailwind.read_text()
    assert "../../design-system/geist-tokens.css" in public_css.read_text()
    assert "../../design-system/geist-tokens.css" in admin_css.read_text()


def test_geist_font_is_self_hosted_in_public_and_admin() -> None:
    """字体自托管：vendored woff2 经共享设计系统引入，且**不依赖** npm 包。

    历史：本断言原先检查 ``dependencies["geist"] == "1.7.2"``。
    ``0942547``（2026-08-20）为消除高危 npm audit 漏洞移除了这个**未被使用**的依赖，
    断言随之失效，并阻断了部署通道 46 天
    （见 ``docs/spec/phases/L1-instrument.md`` §7.1）。

    现改为校验真正的自托管意图——本地 woff2 + ``@font-face`` 相对路径 + 无 npm 依赖——
    使这条测试从"与安全修复矛盾"变成"守护安全修复"。
    """
    design_system = REPO_ROOT / "frontend" / "design-system"
    token_css = (design_system / "geist-tokens.css").read_text()
    assert "@font-face" in token_css

    for font in ("Geist-Variable.woff2", "GeistMono-Variable.woff2"):
        assert (design_system / "fonts" / font).exists()
        assert f"./fonts/{font}" in token_css

    for frontend in ("public", "admin"):
        package_json = REPO_ROOT / "frontend" / frontend / "package.json"
        data = json.loads(package_json.read_text())
        for section in ("dependencies", "devDependencies"):
            assert "geist" not in data.get(section, {}), (
                f"frontend/{frontend} 不应依赖 npm geist 包："
                "字体已 vendored 自托管，该依赖曾引入高危 npm audit 漏洞（0942547）"
            )


def test_vite_dev_servers_allow_shared_design_system_assets() -> None:
    for frontend in ("public", "admin"):
        vite_config = REPO_ROOT / "frontend" / frontend / "vite.config.ts"
        text = vite_config.read_text()
        assert "fs:" in text
        assert 'allow: [path.resolve(__dirname, "..")]' in text
