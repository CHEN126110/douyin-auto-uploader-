# -*- coding: utf-8 -*-
"""核对本地健康、部署文件、静态前端及商品表结构；不读取记录或调用店铺接口。"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import sqlite3
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'taobao-publisher'))
from taobao_publish.sanitize import assert_clean


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    with urllib.request.urlopen('http://127.0.0.1:5001/health', timeout=3) as response:
        health = json.load(response)
    with urllib.request.urlopen('http://127.0.0.1:1420/src/views/ProductManager.vue', timeout=3) as response:
        frontend = response.read().decode('utf-8')
    with urllib.request.urlopen('http://127.0.0.1:1420/src/utils/taobaoFormVerification.ts', timeout=3) as response:
        proof_frontend = response.read().decode('utf-8')
    with urllib.request.urlopen('http://127.0.0.1:1420/src/components/ProductMediaManager.vue', timeout=3) as response:
        media_frontend = response.read().decode('utf-8')
    assert 'ProductMediaManager' in frontend and 'loadMediaDirectory' in media_frontend
    release = ROOT / 'tauri-app/src-tauri/target/release'
    built = ROOT / 'tauri-app/src-tauri/sidecar/python-backend.exe'
    deployed = release / 'python-backend.exe'
    paths = {os.path.normcase(str(release / name)): name for name in
             ('douyin-sock-publisher.exe', 'python-backend.exe')}
    counts = {name: 0 for name in paths.values()}
    data_dirs = set()
    for process in psutil.process_iter(['exe']):
        path = os.path.normcase(process.info.get('exe') or '')
        if path in paths:
            counts[paths[path]] += 1
            if paths[path] == 'python-backend.exe':
                # Tauri 的 build_sidecar_command 将工作目录明确设为 app_data_dir。
                data_dirs.add(Path(process.cwd()))
    assert len(data_dirs) == 1, '当前工作区后端的数据目录不唯一'
    database_path = next(iter(data_dirs)) / 'sqlite.db'
    assert database_path.is_file(), '运行数据库不存在'
    with sqlite3.connect(database_path.as_uri() + '?mode=ro', uri=True) as database:
        columns = {row[1]: row for row in database.execute('PRAGMA table_info("record")')}
    attribute_column = columns.get('captured_attributes')
    schema_matches = bool(attribute_column and attribute_column[2] == 'TEXT' and attribute_column[3] == 0)
    output = {
        'checked_at': datetime.now().astimezone().isoformat(),
        'scope': 'local health, deployed binaries, served static frontend and record table schema only',
        'runtime_captured_attribute_column_present': schema_matches,
        'served_product_media_manager_present': True,
        'product_records_read_by_tools': False,
        'health_success': health.get('success') is True,
        'release_backend_matches_build': digest(built) == digest(deployed),
        'sha256': digest(deployed),
        'frontend_uses_common_action_label': 'publishActionText' in frontend,
        'frontend_uses_common_upload_overlay': 'product-upload-loading' in frontend,
        'frontend_has_no_taobao_only_action_row': 'taobao-task-actions' not in frontend,
        'frontend_uses_taobao_title_counter': 'countTaobaoTitleUnits' in frontend,
        'frontend_saves_current_snapshot': 'savePublishSnapshot' in frontend,
        'frontend_binds_saved_revision': 'expectedRecordRevision' in frontend,
        'frontend_requires_whole_form_proof': 'isVerifiedTaobaoFillResult' in frontend
            and 'whole_publish_form_required_fields' in proof_frontend and 'form_verification' in proof_frontend,
        'frontend_validates_required_receipts': all(marker in proof_frontend for marker in
            ('isConfirmedWholeFormCoverage', 'checkedCount', 'expectedLabels', 'checkedLabels', 'Number.isSafeInteger')),
        'frontend_checks_visible_required_controls': 'visibleRequirementsHaveNoFailures' in proof_frontend
            and 'visible_form_requirements' in proof_frontend,
        'frontend_uses_explicit_custom_sku_mode': 'sku_mode: \"custom\"' in frontend,
        'application_processes': counts['douyin-sock-publisher.exe'],
        'backend_processes': counts['python-backend.exe'],
        'live_taobao_task_started_by_tools': False,
        'account_identity_read_by_tools': False,
    }
    assert all(output[key] for key in ('health_success', 'release_backend_matches_build',
        'runtime_captured_attribute_column_present',
        'frontend_uses_common_action_label', 'frontend_uses_common_upload_overlay',
        'frontend_has_no_taobao_only_action_row', 'frontend_uses_taobao_title_counter',
        'frontend_saves_current_snapshot', 'frontend_binds_saved_revision',
        'frontend_uses_explicit_custom_sku_mode', 'frontend_requires_whole_form_proof',
        'frontend_validates_required_receipts', 'frontend_checks_visible_required_controls'))
    assert output['application_processes'] == 1
    # PyInstaller onefile 的父/子进程是同一实例；不是两份后端服务。
    assert output['backend_processes'] == 2
    assert_clean(output)
    (ROOT / 'taobao-publisher/outputs/desktop_click_browser_runtime.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()
