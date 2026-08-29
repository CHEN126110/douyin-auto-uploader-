# -*- coding: utf-8 -*-
"""平台材质选项采集与缓存的回归测试（2026-08-28）。

平台该类目实际下发 144 项材质（见 tmp_runtime_probe_live/fxg_category_matrix_socks_*.json
中属性 id=785 的 optionCount），而内置 PLATFORM_MATERIAL_OPTIONS 只有十余项。
因此改为在发布流程打开材质下拉时顺带采集平台真实列表并缓存，设置界面据此展示。

核心不变量：采集是纯增益动作——失败绝不覆盖已有缓存、绝不影响发布主流程、绝不静默。
"""

import io
import json
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

UTILS_PY = os.path.join(REPO_ROOT, 'src', 'utils.py')
BUILD_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'build_sidecar.py')
SPEC_PY = os.path.join(REPO_ROOT, 'tauri-app', 'python-sidecar', 'python-backend.spec')


@pytest.fixture()
def cache(monkeypatch):
    """把缓存重定向到临时目录，避免污染真实运行数据。"""
    from src import material_options_cache as mod

    tmpdir = tempfile.mkdtemp()
    target = os.path.join(tmpdir, mod.CACHE_FILENAME)
    monkeypatch.setattr(mod, 'resolve_cache_path', lambda: target)
    return mod


def test_save_and_load_roundtrip(cache):
    options = [f'材质{i}' for i in range(30)]
    assert cache.save_options('袜子 > 中筒袜', options) is True
    assert cache.load_options('袜子 > 中筒袜') == options
    assert cache.load_meta()['option_count'] == 30


def test_failure_never_overwrites_existing_cache(cache):
    good = [f'材质{i}' for i in range(30)]
    assert cache.save_options('袜子', good) is True

    # 采到的条数过少：多半是没滚完，必须保留旧值
    assert cache.save_options('袜子', ['棉', '氨纶']) is False
    assert cache.load_options('袜子') == good
    assert 'too few options' in cache.load_meta()['last_error']

    # 骤减一半以上：同样保留旧值
    assert cache.save_options('袜子', [f'材质{i}' for i in range(10)]) is False
    assert cache.load_options('袜子') == good
    assert 'suspicious shrink' in cache.load_meta()['last_error']


def test_failure_is_recorded_not_swallowed(cache):
    cache.record_failure('dropdown_not_found')
    meta = cache.load_meta()
    assert meta['last_error'] == 'dropdown_not_found'
    assert meta['last_error_at'], '失败必须留下时间戳，便于判断是否为陈旧错误'


def test_corrupt_cache_degrades_to_empty(cache):
    with io.open(cache.resolve_cache_path(), 'w', encoding='utf-8') as handle:
        handle.write('{ this is not valid json')
    assert cache.load_options() == [], '缓存损坏时应安全退化为空，由调用方回退内置默认'


def test_harvest_never_raises_into_publish_flow(cache, monkeypatch):
    """采集失败绝不能把异常抛进发布主流程。"""
    import src.utils as utils
    monkeypatch.setattr(utils, 'get_current_category_text', lambda tab: '袜子', raising=False)

    class ExplodingTab:
        def run_js(self, script, *args, **kwargs):
            raise RuntimeError('CDP boom')

    assert utils.harvest_platform_material_options(ExplodingTab(), '袜子') is False
    assert 'run_js failed' in cache.load_meta()['last_error']


def test_harvest_rejects_filtered_subset(cache, monkeypatch):
    """搜索框非空时读到的是过滤子集，绝不能当成全量写入。"""
    import src.utils as utils

    class FilteredTab:
        def run_js(self, script, *args, **kwargs):
            return json.dumps({'ok': False, 'reason': 'search_not_empty'})

    assert utils.harvest_platform_material_options(FilteredTab(), '袜子') is False
    assert cache.load_options('袜子') == []
    assert cache.load_meta()['last_error'] == 'search_not_empty'


def test_harvest_happy_path(cache, monkeypatch):
    import src.utils as utils
    options = [f'材质{i}' for i in range(40)]

    class GoodTab:
        def run_js(self, script, *args, **kwargs):
            return json.dumps({'ok': True, 'source': 'fiber', 'options': options})

    assert utils.harvest_platform_material_options(GoodTab(), '袜子 > 中筒袜') is True
    assert cache.load_options('袜子 > 中筒袜') == options


def test_harvest_runs_before_search_input():
    """采集必须发生在下拉打开之后、输入搜索词之前。"""
    source = io.open(UTILS_PY, encoding='utf-8').read()
    body = source.split('def _fill_aurora_composition_select', 1)[1].split('\ndef ', 1)[0]
    harvest_pos = body.find('harvest_platform_material_options(new_tab')
    search_pos = body.find('输入搜索过滤')
    assert harvest_pos != -1, '填写路径必须调用采集'
    assert search_pos != -1, '未找到搜索过滤段落，请同步更新本测试'
    assert harvest_pos < search_pos, '采集必须早于输入搜索词，否则只会采到过滤后的子集'


def test_new_module_registered_for_pyinstaller():
    """新模块必须登记 hiddenimports，否则打包后 No module named。"""
    assert 'src.material_options_cache' in io.open(BUILD_PY, encoding='utf-8').read()
    assert 'src.material_options_cache' in io.open(SPEC_PY, encoding='utf-8').read()
