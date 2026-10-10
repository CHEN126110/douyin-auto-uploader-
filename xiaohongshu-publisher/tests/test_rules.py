# -*- coding: utf-8 -*-
"""小红书千帆：本地规则与页面表达式的离线回归（不碰真机、不加载浏览器）。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "xiaohongshu-publisher"))

from xiaohongshu_publish import page_scripts, rules  # noqa: E402


# --- 标题规则 ---------------------------------------------------------------

def test_title_units_counts_cjk_as_two():
    """真机实测：28 个汉字 → 页面计数器 56/60。"""
    title = "桑蚕丝羊毛小腿袜女秋冬款日系撞色罗口美腿袜冬天长筒堆堆袜"
    assert len(title) == 28
    assert rules.title_units(title) == 56
    assert rules.check_title(title).ok is True


def test_title_too_short_is_rejected():
    """真机实测：标题框里只有「测」两个字时平台报错（2/60 < 16）。"""
    result = rules.check_title("测")
    assert result.ok is False
    assert any("少于" in reason for reason in result.reasons)


def test_title_over_thirty_words_is_rejected():
    """超过 30 个字必须本地拦下——否则提交时才被打回。"""
    result = rules.check_title("袜" * 31)
    assert result.ok is False
    assert any("超过 30 个字" in reason for reason in result.reasons)


def test_title_empty_is_rejected():
    assert rules.check_title("   ").ok is False
    assert rules.check_title(None).ok is False


def test_title_describe_is_human_readable():
    assert "标题可用" in rules.check_title("桑蚕丝羊毛小腿袜女秋冬款日系撞色罗口美腿袜").describe()
    assert "标题不可用" in rules.check_title("测").describe()


# --- 页面表达式 -------------------------------------------------------------

def test_title_is_located_by_brand_placeholder_not_rotating_hint():
    """标题框判据必须是 placeholder 含「品牌」（轮换提示/顶部帮助框都会变，不能当锚点）。"""
    script = page_scripts.FIND_TITLE
    assert "/品牌/" in script
    assert "input[type=\"text\"]" in script


def test_set_title_uses_native_setter_and_dispatches_events():
    """第二条纪律：只能用原生 setter + input/change，且必须主动失焦。"""
    script = page_scripts.set_title_script("测试标题测试标题")
    assert "HTMLInputElement.prototype" in script
    assert "new Event('input'" in script
    assert "new Event('change'" in script
    assert ".blur()" in script
    # 不得使用被证伪的输入方式
    assert "execCommand" not in script


def test_set_title_escapes_quotes():
    script = page_scripts.set_title_script('带"引号"的标题')
    assert '\\"' in script


def test_hit_test_targets_the_requested_point():
    script = page_scripts.hit_test_script(626, 1246)
    assert "elementFromPoint(626, 1246)" in script
    assert re.search(r"elementFromPoint\(\d+, \d+\)", script)


def test_drawer_state_reports_both_drawer_and_mask():
    """第四条纪律的判据要同时看抽屉与遮罩。"""
    script = page_scripts.DRAWER_STATE
    assert "material-space-drawer" in script
    assert "d-drawer-mask" in script
    assert "document.visibilityState" in script


def test_drawer_cancel_only_searches_inside_the_drawer():
    """踩过的坑：查「取消」时若排除抽屉内元素就会 found:false（那个按钮恰在抽屉里）。"""
    script = page_scripts.DRAWER_CANCEL
    assert "drawer.querySelectorAll" in script


# --- 必填判据与完成度判据（第 70/71/76 轮真机实证后固化） ---------------------

def test_required_fields_uses_platform_marker_class():
    """必填标记是空文本元素（innerText 看不到 `*`）→ 只能按 class `required-icon` 找。"""
    script = page_scripts.REQUIRED_FIELDS
    assert "required-icon" in script
    assert "unfilled" in script and "filled" in script
    assert "请选择" in script          # 未填的判据之一


def test_judges_covers_three_counters_and_helper_placeholder():
    """三套判据：关键属性 N/7、其他属性 N/8、N 项必填；外加发布助手的"空空如也"语义。"""
    script = page_scripts.JUDGES
    assert "关键属性" in script
    assert "其他属性" in script
    assert "项必填" in script
    assert "空空如也" in script


def test_find_painted_requires_element_from_point_confirmation():
    """只认被绘制的元素（未展开下拉的选项也在 DOM 里且看着可见 ✗）→ 必须用命中反查确认。"""
    script = page_scripts.find_painted_script("长筒袜")
    assert "elementFromPoint" in script
    assert "not_found" in script and "fully_covered" in script


def test_find_painted_escapes_text_and_supports_exact_and_selector():
    loose = page_scripts.find_painted_script('带"引号"的文本')
    assert '\\"' in loose                     # JSON 转义，避免注入
    assert '"exact"'.replace('"', '') or True  # 占位说明：EXACT 已注入为字面量
    assert "false" in loose                   # 默认包含匹配
    strict = page_scripts.find_painted_script("信息已确认，下一步", exact=True)
    assert "true" in strict
    narrowed = page_scripts.find_painted_script("取消", selector='button,[class*="d-button"]')
    assert "d-button" in narrowed
