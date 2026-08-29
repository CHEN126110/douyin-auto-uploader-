# -*- coding: utf-8 -*-
"""自定义材质支持的回归测试（2026-08-28）。

原实现把材质锁死在 src/config.py 的 PLATFORM_MATERIAL_OPTIONS 白名单上，共三层：
  1. 前端 SettingsPanel.vue：addMaterialComposition 拒绝非白名单项、
     materialSettingsInvalid 把非白名单项判为无效；
  2. 后端保存接口 app.py：`材质「x」不在平台面料选项内`；
  3. src/config.py normalize_automation_config：**静默过滤**掉非白名单项
     （最隐蔽的一层——保存看似成功，实际配置里那条材质消失了）。

平台会持续新增面料，写死白名单会把新材质和用户自定义材质一起挡在外面。
现在三层都放开，只保留「非空 + 长度上限 + 含量合计 100%」这些真正的数据约束。
"""

import io
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.config import (  # noqa: E402
    MATERIAL_NAME_MAX_LENGTH,
    PLATFORM_MATERIAL_OPTIONS,
    SettingsManager,
)

APP_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'app.py')
PANEL_VUE = os.path.join(REPO_ROOT, 'tauri-app', 'src', 'components', 'SettingsPanel.vue')

CUSTOM = '自定义纤维A'


def test_custom_material_survives_normalization():
    """核心回归：自定义材质不能在归一化时被静默丢弃。"""
    assert CUSTOM not in PLATFORM_MATERIAL_OPTIONS, '用例前提：该材质不在内置白名单里'
    result = SettingsManager.normalize_automation_config({
        'material_options': ['棉', CUSTOM],
        'material_compositions': [
            {'material': CUSTOM, 'percentage': 60},
            {'material': '棉', 'percentage': 40},
        ],
    })
    names = [item['material'] for item in result['material_compositions']]
    assert CUSTOM in names, '自定义材质被静默丢弃了'
    assert CUSTOM in result['material_options'], '自定义材质未保留在可选列表中'


def test_platform_fetched_options_are_kept():
    """从平台拉取的新材质必须原样保留，不能被内置白名单过滤。"""
    fetched = ['棉', '氨纶', '平台新增面料X', '平台新增面料Y']
    result = SettingsManager.normalize_automation_config({'material_options': fetched})
    for name in fetched:
        assert name in result['material_options'], f'平台材质 {name} 被过滤掉了'


def test_normalization_still_cleans_dirty_input():
    """放开白名单不等于放弃数据卫生：空白项去除、去重、超长拒绝。"""
    result = SettingsManager.normalize_automation_config({
        'material_options': ['棉', '  ', '棉', 'x' * (MATERIAL_NAME_MAX_LENGTH + 1)],
        'material_compositions': [
            {'material': '  ', 'percentage': 50},
            {'material': 'y' * (MATERIAL_NAME_MAX_LENGTH + 1), 'percentage': 50},
        ],
    })
    assert result['material_options'] == ['棉'], '空白/重复/超长项应被清理'
    names = [item['material'] for item in result['material_compositions']]
    assert all(name.strip() for name in names), '空材质名不应保留'
    assert all(len(name) <= MATERIAL_NAME_MAX_LENGTH for name in names), '超长材质名不应保留'


def test_backend_save_no_longer_rejects_custom_material():
    source = io.open(APP_PY, encoding='utf-8').read()
    assert '不在平台面料选项内' not in source, \
        '保存接口不应再按内置白名单拒绝自定义材质'
    assert 'MATERIAL_NAME_MAX_LENGTH' in source, \
        '放开白名单后仍需保留长度上限这类真实数据约束'
    assert '材质面料含量总和必须等于100' in source, \
        '含量合计 100% 是真实业务约束，不能一并放开'


def test_frontend_allows_custom_material_input():
    source = io.open(PANEL_VUE, encoding='utf-8').read()
    assert '材质不在平台可选列表内' not in source, '前端不应再拒绝自定义材质'
    # 两处材质下拉都必须可输入（filterable + allow-create）
    assert source.count('allow-create') >= 3, '材质下拉需支持 allow-create 自定义输入'
    assert 'isCustomMaterial' in source, '应保留自定义材质的识别逻辑用于提示'
    assert 'customMaterialNames' in source, '应向用户提示哪些是自定义材质'
