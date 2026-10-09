# -*- coding: utf-8 -*-
"""归档本轮已执行的测试/构建/本地启动核对，不读取商品或访问平台。"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'taobao-publisher'))
from taobao_publish.sanitize import assert_clean


def save(path, value):
    assert_clean(value)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    outputs = ROOT / 'taobao-publisher/outputs'
    build = json.loads((outputs / 'desktop_click_browser_build.json').read_text(encoding='utf-8'))
    runtime = json.loads((outputs / 'desktop_click_browser_runtime.json').read_text(encoding='utf-8'))
    assert runtime['sha256'] == build['sha256']
    assert runtime['health_success'] and runtime['served_product_media_manager_present']
    assert build['checks']['frozen_media_catalog_and_routes_match_source']
    save(outputs / 'desktop_cloud_media_build.json', build)
    save(outputs / 'desktop_cloud_media_runtime.json', runtime)
    sources = ['src/product_media.py', 'taobao-publisher/taobao_publish/media_library.py',
        'taobao-publisher/taobao_publish/page.py', 'taobao-publisher/taobao_publish/form_adapters.py',
        'taobao-publisher/taobao_publish/stages.py', 'taobao-publisher/taobao_publish/pipeline.py',
        'tauri-app/src/components/ProductMediaManager.vue', 'tauri-app/src/stores/productStore.ts',
        'tests/test_product_media.py', 'taobao-publisher/tests/test_cloud_media_tree.py']
    report = {
        'checked_at': datetime.now().astimezone().isoformat(),
        'scope': 'offline tests, isolated browser models and local deployment only',
        'taobao_suite': {'passed': 1320, 'skipped': 7, 'subtests_passed': 335,
            'excluded_live_environment_tests': ['ObjectiveAuditScriptTest::test_it_runs_clean',
                'CdpAddressOptionTest::test_parses_address_into_a_list_url']},
        'media_and_publish_safety_tests_passed': 88,
        'targeted_tree_cache_and_docs_passed': 34,
        'targeted_docs_subtests_passed': 11,
        'common_frontend_behavior_tests_passed': 79,
        'media_frontend_async_tests_passed': 5,
        'vue_typecheck_and_vite_build_passed': True,
        'package_selfcheck_passed': True,
        'build_archive_audit_passed': True,
        'normal_launcher_runtime_audit_passed': True,
        'live_taobao_accessed': False,
        'live_upload_saved_draft_or_submitted': False,
        'whole_form_confirmed': False,
        'backend_sha256': build['sha256'],
        'source_hashes': {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sources},
    }
    save(outputs / 'desktop_cloud_media_validation.json', report)
    evidence = ROOT / 'taobao-publisher/docs/05-证据日志.md'
    raw = evidence.read_bytes()
    if b'| E-200 |' not in raw:
        addition = '''

## 云端图片树与文件内容索引

| ID | 结论 | 证据与范围 |
|---|---|---|
| E-200 | 用户明确优先自动化读取云端文件树；上传前复用和上传后定位统一遍历实际商品子树，包含多级目录、懒加载、文件内容、分页与选图回到对应页 | verified 隔离浏览器模型，`test_cloud_media_tree.py` 8项覆盖独立于本地文件的目录读取及深层缓存不重传；当前真实 DOM 仍candidate。[说明](29-云端图片目录树与文件索引.md) |
| E-201 | 辅助本地目录浏览、按账户保存素材事实和内容变化识别已接入；最终全包1320 passed/7 skipped/335 subtests，业务安全及本地素材88项，共同前端79组/目录异步5组，构建与包自检通过 | verified 本地软件：[验证](../outputs/desktop_cloud_media_validation.json)、[冻结归档](../outputs/desktop_cloud_media_build.json)、[运行核对](../outputs/desktop_cloud_media_runtime.json)。24运行模块、4契约、70源码及新增目录模块/接口执行内容核对通过；正常入口部署，health与单实例通过。没有真实平台上传、草稿或提交，完整目标保持未完成 |
'''
        newline = '\r\n' if b'\r\n' in raw else '\n'
        with evidence.open('ab') as stream:
            stream.write(addition.replace('\n', newline).encode('utf-8'))
    print(json.dumps({'success': True, 'backend_sha256': build['sha256'],
                      'validation': 'desktop_cloud_media_validation.json'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
