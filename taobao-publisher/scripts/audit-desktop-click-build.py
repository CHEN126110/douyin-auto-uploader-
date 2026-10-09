# -*- coding: utf-8 -*-
"""离线核对冻结后端里的点击启动路径；不连接应用、浏览器或平台。"""
from __future__ import annotations

import ast
import dis
from datetime import datetime
import hashlib
import json
import marshal
from pathlib import Path
import sys
import types

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'taobao-publisher'))
from taobao_publish.sanitize import assert_clean


def code_objects(code):
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from code_objects(value)


def code_signature(code):
    """忽略部署文件名/行位置，比较冻结代码与源码编译后的执行内容。"""
    def constant(value):
        if isinstance(value, types.CodeType):
            return code_signature(value)
        if isinstance(value, tuple):
            return tuple(constant(item) for item in value)
        return value
    return (code.co_code, tuple(constant(value) for value in code.co_consts),
            code.co_names, code.co_varnames, code.co_freevars, code.co_cellvars,
            code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount, code.co_flags,
            code.co_stacksize, code.co_exceptiontable)


def runtime_closure():
    """从实际桌面入口出发，跟进同包 import；不要求 CLI 模块进入桌面 EXE。"""
    package = ROOT / 'taobao-publisher/taobao_publish'
    pending = ['taobao_publish', 'taobao_publish.desktop', 'taobao_publish.pipeline']
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        path = package / ('__init__.py' if name == 'taobao_publish' else name.split('.')[-1] + '.py')
        if not path.is_file():
            raise ValueError('运行模块源码不存在：' + name)
        visited.add(name)
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom):
                if node.level and node.module:
                    pending.append('taobao_publish.' + node.module)
                elif node.level:
                    pending.extend('taobao_publish.' + alias.name for alias in node.names)
                elif node.module and node.module.startswith('taobao_publish'):
                    pending.append(node.module)
            elif isinstance(node, ast.Import):
                pending.extend(alias.name for alias in node.names if alias.name.startswith('taobao_publish'))
    return sorted(visited)


def main():
    exe = ROOT / 'tauri-app/src-tauri/sidecar/python-backend.exe'
    archive = CArchiveReader(str(exe))
    main_code = marshal.loads(archive.extract('app'))
    functions = {code.co_name: code for code in code_objects(main_code)}
    pyz_name = next(name for name in archive.toc if name.endswith('.pyz'))
    pyz = archive.open_embedded_archive(pyz_name)
    app_source = ROOT / 'tauri-app/python-sidecar/app.py'
    source_functions = {code.co_name: code for code in code_objects(compile(app_source.read_bytes(), str(app_source), 'exec', dont_inherit=True))}
    for name in ('_load_capture_attributes', '_capture_product_attributes', '_product_edit_revision',
                 '_import_capture_product_record', 'import_capture_result',
                 '_capture_taobao_tmall_product_for_store', 'start_capture'):
        assert code_signature(functions[name]) == code_signature(source_functions[name]), '冻结采集交接函数与源码不同：' + name
    orm_source = ROOT / 'src/orm.py'
    assert code_signature(pyz.extract('src.orm')) == code_signature(compile(orm_source.read_bytes(), str(orm_source), 'exec', dont_inherit=True))
    media_source = ROOT / 'src/product_media.py'
    assert code_signature(pyz.extract('src.product_media')) == code_signature(compile(media_source.read_bytes(), str(media_source), 'exec', dont_inherit=True))
    for name in ('product_media_list', 'product_media_image', '_run_taobao_publish_task'):
        assert code_signature(functions[name]) == code_signature(source_functions[name]), '冻结图片目录接口与源码不同：' + name
    modules = runtime_closure()
    assert all(name in pyz.toc for name in modules)
    package_source = ROOT / 'taobao-publisher/taobao_publish'
    for name in modules:
        source_path = package_source / ('__init__.py' if name == 'taobao_publish' else name.split('.')[-1] + '.py')
        source_code = compile(source_path.read_bytes(), str(source_path), 'exec', dont_inherit=True, optimize=0)
        assert code_signature(pyz.extract(name)) == code_signature(source_code), '冻结代码与源码执行内容不同：' + name
    contracts = ('field_mapping.json', 'selectors.json', 'rules.json', 'publish_item.schema.json')
    assert all('taobao-publisher/contracts/' + name in archive.toc or
               'taobao-publisher\\contracts\\' + name in archive.toc for name in contracts)
    checks = {
        'frozen_media_catalog_and_routes_match_source': True,
        'frozen_capture_storage_and_migration_match_source': True,
        'frozen_package_semantics_match_current_source': True,
        'start_calls_browser_bootstrap': '_ensure_taobao_fill_browser' in functions['taobao_publish_start'].co_names,
        'bootstrap_uses_account_lifecycle': '_activate_shop_profile' in functions['_ensure_taobao_fill_browser'].co_names,
        'bootstrap_uses_current_account': '_active_shop_account' in functions['_ensure_taobao_fill_browser'].co_names,
        'start_preserves_in_flight_guard': '_account_change_blocked' in functions['taobao_publish_start'].co_names,
        'account_change_covers_taobao': '_taobao_tasks' in functions['_account_change_blocked'].co_names,
        'fill_only_argument': 'fill_only' in functions['taobao_publish_start'].co_consts,
        'submit_stop_argument': 'stop_before_submit' in functions['taobao_publish_start'].co_consts,
        'http_text_gate_reads_contract': all(name in functions['_taobao_product_request_payload'].co_varnames
                                            for name in ('text_rules', 'desktop_text', 'maximum')),
        'save_validates_before_write': '_validated_product_edits' in functions['save_info'].co_names,
        'save_returns_record_revision': '_product_edit_revision' in functions['save_info'].co_names,
        'douyin_start_checks_record_revision': '_require_product_revision' in functions['upload_start'].co_names,
        'taobao_start_checks_record_revision': '_require_product_revision' in functions['taobao_publish_start'].co_names,
    }
    def module_functions(name):
        return {code.co_name: code for code in code_objects(pyz.extract(name))}

    mapping = module_functions('taobao_publish.mapping')
    stages = module_functions('taobao_publish.stages')
    source = module_functions('taobao_publish.local_source')
    adapters = module_functions('taobao_publish.form_adapters')
    flow = module_functions('taobao_publish.pipeline')
    page_functions = module_functions('taobao_publish.page')
    library = module_functions('taobao_publish.media_library')
    # verification 模块只含纯函数；实际执行冻结代码核验回执反例，不接触平台。
    proof_namespace = {}
    exec(pyz.extract('taobao_publish.verification'), proof_namespace)
    proof_check = proof_namespace['whole_form_coverage_confirmed']
    native_check = proof_namespace['visible_requirements_have_no_failures']
    proof = {'known': True, 'completePage': True, 'scope': 'whole_publish_form_required_fields',
             'rowCount': 1, 'required': [{'label': 'model_required', 'hitCount': 1, 'supportedReader': True}],
             'checked': [{'label': 'model_required', 'value': 'model_value'}], 'checkedCount': 1}
    empty = dict(proof, required=[], checked=[], checkedCount=0)
    contradiction = dict(proof, required=proof['required'] + [{'label': 'second_required', 'hitCount': 1, 'supportedReader': True}],
                         checked=proof['checked'] + [{'label': 'second_required', 'value': 'second_value'}], checkedCount=2)
    checks.update({
        'frozen_required_proof_accepts_consistent_receipts': proof_check(proof) is True,
        'frozen_native_required_facts_reject_unknown': native_check({'known': False}) is False,
        'frozen_native_required_facts_reject_missing_choice': native_check({
            'known': True, 'completePage': False, 'scope': 'visible_publish_rows_required',
            'rowCount': 1, 'unownedRequiredCount': 0, 'required': [{'label': 'required_choice',
            'hitCount': 1, 'supportedReader': True, 'filled': False, 'valid': True}]}) is False,
        'frozen_required_proof_rejects_empty_receipts': proof_check(empty) is False,
        'frozen_required_proof_rejects_contradictory_row_count': proof_check(contradiction) is False,
    })
    session_bytecode = list(dis.get_instructions(stages['stage_session']))
    checks.update({
        'session_does_not_wait_for_form': any(
            instruction.opname == 'LOAD_CONST' and instruction.argval is False
            and index + 1 < len(session_bytecode)
            and session_bytecode[index + 1].opname == 'KW_NAMES'
            and stages['stage_session'].co_consts[session_bytecode[index + 1].arg] == ('wait_form',)
            for index, instruction in enumerate(session_bytecode)),
        'session_failure_is_not_success': 'failed' in stages['stage_session'].co_names,
        'session_has_no_duplicate_health_check': 'health_check' not in stages['stage_session'].co_names,
        'opener_preserves_renderer_error': 'RendererHungError' in stages['_open_publish_page'].co_names,
        'page_facts_reject_incomplete_data': 'PageError' in page_functions['read_page_facts'].co_names,
        'precheck_defers_later_controls': 'stage_adapter_blockers' in stages['stage_precheck'].co_names
            and 'deferred_adapter_blockers' in stages['stage_precheck'].co_consts,
        'stage_executor_checks_its_controls': '_stage_adapter_guard' in stages['run_stage'].co_names,
        'runtime_controls_require_handler_declaration':
            'runtime_selector_keys' in stages['_stage_adapter_guard'].co_names,
        'direct_upload_checks_before_actions': '_stage_adapter_guard' in stages['stage_upload_images'].co_names,
        'direct_sku_checks_before_actions': '_stage_adapter_guard' in stages['stage_fill_skus'].co_names,
        'direct_detail_checks_before_actions': '_stage_adapter_guard' in stages['stage_fill_detail'].co_names,
        'media_configuration_is_scoped': 'media' in adapters['prepare_media'].co_consts,
        'sku_configuration_is_scoped': 'sku' in adapters['create_custom_skus'].co_consts,
        'detail_configuration_is_scoped': 'detail' in adapters['fill_detail'].co_consts,
        'readback_configuration_is_scoped': 'readback' in adapters['verify_bound_media'].co_consts,
        'default_no_brand_policy': '无品牌' in stages['stage_select_category'].co_consts
            and 'brand_defaulted' in stages['stage_select_category'].co_varnames,
        'brand_next_waits_for_enablement': 'wait_for_confirm_button' in stages['stage_select_category'].co_names,
        'selected_brand_is_carried_forward': 'PropEntry' in stages['stage_select_category'].co_names,
        'main_images_use_content_identity': 'media_file_identity' in stages['stage_upload_images'].co_names,
        'main_images_check_selected_url': 'expected_urls' in stages['stage_upload_images'].co_varnames,
        'upload_snapshots_before_browser': 'copy2' in page_functions['upload_files_to_media'].co_names
            and '_upload_staged_files_to_media' in page_functions['upload_files_to_media'].co_names,
        'upload_checks_expected_digest': 'MediaSourceChangedError' in page_functions['upload_files_to_media'].co_names,
        'upload_waits_for_queue_before_finish': 'wait_for_media_upload_queue' in page_functions['_upload_staged_files_to_media'].co_names
            and 'wait_for_media_images' not in page_functions['_upload_staged_files_to_media'].co_names,
        'main_media_reads_actual_product_tree': 'find_product_images' in adapters['prepare_media'].co_names,
        'main_media_records_actual_uploaded_directory': 'locate_uploaded_images' in adapters['prepare_media'].co_names,
        'uploaded_media_searches_actual_subtree': 'find_product_images' in library['locate_uploaded_images'].co_names
            and 'product_directory_tree' in library['find_product_images'].co_names,
        'folder_listing_reads_remote_files': 'list_media_images' in library['read_directory_files'].co_names,
        'selection_returns_to_recorded_page': 'open_media_page' in page_functions['select_media_image'].co_names,
        'directory_selection_waits_for_gallery_loading': 'wait_for_media_gallery_ready' in library['open_directory'].co_names,
        'inventory_rejects_loading_restart': 'require_media_gallery_still_ready' in page_functions['list_media_images'].co_names,
        'batch_lookup_rejects_loading_restart': 'require_media_gallery_still_ready' in page_functions['find_media_images'].co_names,
        'media_selection_waits_for_gallery_loading': 'wait_for_media_gallery_ready' in page_functions['select_media_image'].co_names,
        'media_lookup_supports_owned_captions': any(isinstance(value, str) and 'nameBelongsToCard' in value
            for value in page_functions['_build_media_lookup_expression'].co_consts),
        'sku_media_returns_to_recorded_directory': 'open_directory' in adapters['create_custom_skus'].co_names,
        'gallery_readback_confirms_selected_path': 'read_directory' in library['open_directory'].co_names,
        'selected_parent_can_still_expand': 'expand' in library['open_directory'].co_varnames,
        'media_stage_reports_substeps': 'report_media_activity' in stages['stage_upload_images'].co_names,
        'pipeline_reports_form_verification': 'summarize_form_verification' in flow['finish'].co_names,
        'readback_checks_visible_required_controls': '_read_required_form_controls' in stages['stage_readback'].co_names,
        'required_control_reader_is_wired': 'read_required_form' in stages['_read_required_form_controls'].co_names,
        'full_coverage_must_include_native_required_fields': 'covered_labels' in proof_namespace['summarize_form_verification'].__code__.co_cellvars,
        'worker_requires_whole_form_proof': 'whole_form_coverage_confirmed' in functions['_run_taobao_publish_task'].co_names,
        'freight_uses_current_page_selection': 'from_page_selection' in stages['stage_fill_freight'].co_varnames,
        'custom_mode_http_translation': 'sku_mode' in functions['_taobao_product_request_payload'].co_varnames,
        'custom_sku_route_wired': '_stage_fill_custom_skus' in stages['stage_fill_skus'].co_names,
        'extra_media_preparation_wired': 'prepare_media' in stages['stage_upload_images'].co_names,
        'detail_handler_wired': 'fill_detail' in stages['stage_fill_detail'].co_names,
        'final_media_readback_wired': 'verify_bound_media' in stages['stage_readback'].co_names,
        'candidate_controls_require_supported_runtime_guards': 'selector_has_execution_guard' in adapters['adapter_blockers'].co_names
            and 'probe' in adapters['create_custom_skus'].co_consts,
        'media_lookup_uses_shared_card_handler': 'find_media_image' in adapters['gallery_find'].co_names
            and 'select_media_image' in adapters['gallery_find'].co_names,
        'main_cache_requires_card_receipt': 'prepare_media' in stages['stage_upload_images'].co_names
            and 'find_media_images' in adapters['prepare_media'].co_names,
        'all_media_roles_use_batch_lookup': 'find_media_images' in adapters['prepare_media'].co_names,
        'all_media_roles_share_upload_preparation': 'upload_files_to_media' in adapters['prepare_media'].co_names
            and 'upload_files_to_media' not in stages['stage_upload_images'].co_names,
        'upload_destination_is_checked': 'ensure_all_images' in page_functions['_upload_staged_files_to_media'].co_names,
        'each_main_slot_reopens_its_picker': 'ensure_media_popup_closed' in stages['stage_upload_images'].co_names,
        'detail_is_a_separate_stage': 'stage_fill_props_and_detail' not in stages and 'stage_fill_detail' in stages,
        'weighted_title_precheck': 'count_title_units' in mapping['validate_title'].co_names,
        'weighted_title_write_guard': 'count_title_units' in stages['stage_fill_base'].co_names,
        'unconsumed_media_is_not_success': 'missing_media' in stages['_stage_adapter_guard'].co_varnames,
        'asset_path_guard': '_check_asset_path' in source['_list_images'].co_names,
        'square_assets_preserved': 'square_images' in source['local_product_from_record'].co_names,
        'sku_image_role_projection': any('image_path' in code.co_names
                                        for code in code_objects(mapping['build_publish_item'])),
    })
    selector_resource = next(name for name in archive.toc if name.replace('\\', '/') == 'taobao-publisher/contracts/selectors.json')
    selector_entries = json.loads(archive.extract(selector_resource))['selectors']
    candidate_keys = ('sku.custom_mode', 'sku.custom_rows', 'sku.custom_input', 'sku.custom_add',
                      'sku.image_slot', 'sku.table_image', 'detail.editor', 'media.exact_filename')
    levels = {entry['key']: entry['evidence']['level'] for entry in selector_entries if entry['key'] in candidate_keys}
    checks['offline_fixture_did_not_promote_production_evidence'] = len(levels) == 8 and set(levels.values()) == {'candidate'}
    assert all(checks.values()), checks
    # 构建清单与当前源码一致，不能用旧 EXE 通过归档存在性检查。
    manifest = json.loads((ROOT / 'tauri-app/python-sidecar/.source-manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    output = {
        'checked_at': datetime.now().astimezone().isoformat(),
        'scope': 'offline frozen backend code, runtime imports and build manifest',
        'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
        'size_bytes': exe.stat().st_size,
        'checks': checks,
        'required_runtime_modules': modules,
        'runtime_modules_verified': len(modules),
        'contracts_verified': list(contracts),
        'source_manifest_files_verified': len(manifest['files']),
        'live_platform_fill_executed': False,
    }
    assert_clean(output)
    (ROOT / 'taobao-publisher/outputs/desktop_click_browser_build.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'checks': checks, 'modules': len(modules), 'contracts': len(contracts),
                      'source_files': len(manifest['files'])}, ensure_ascii=False))


if __name__ == '__main__':
    main()
