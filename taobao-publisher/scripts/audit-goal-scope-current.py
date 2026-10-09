"""完整目标的本地审查：只读源码、既有验证产物和允许的本地运行核对结果。

不启动浏览器，不读取平台任务，不请求平台页面，不把候选控件当成无法开发。
本脚本记录验收缺口；目标状态仍须由目标工具确认。
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SUBPROJECT = ROOT / 'taobao-publisher'
sys.path.insert(0, str(SUBPROJECT))
from taobao_publish.sanitize import assert_clean


def load(relative):
    return json.loads((SUBPROJECT / relative).read_text(encoding='utf-8'))


def requirement(key, description, scope, evidence, remaining, status='completion_unproven'):
    return {'id': key, 'requirement': description, 'status': status,
            'available_evidence_scope': scope, 'evidence': evidence,
            'missing_authoritative_evidence': remaining}


def main():
    build = load('outputs/desktop_click_browser_build.json')
    runtime = load('outputs/desktop_click_browser_runtime.json')
    validation = load('outputs/desktop_media_batch_validation.json')
    model = load('outputs/media_batch_five_main_handoff.json')
    captured_model = load('outputs/captured_attribute_pipeline_handoff.json')
    assert all(build['checks'].values())
    assert runtime['health_success'] and runtime['release_backend_matches_build']
    assert runtime['sha256'] == build['sha256']
    assert runtime['sha256'] == hashlib.sha256((ROOT / 'tauri-app/src-tauri/sidecar/python-backend.exe').read_bytes()).hexdigest()
    assert runtime['application_processes'] == 1 and runtime['backend_processes'] == 2
    assert model['live_platform_tested'] is False and captured_model['live_platform_tested'] is False
    assert model['result']['data']['form_verification']['complete'] is False
    assert captured_model['result']['data']['form_verification']['complete'] is False

    selectors = load('contracts/selectors.json')['selectors']
    active_keys = {'sku.custom_mode', 'sku.custom_rows', 'sku.custom_input', 'sku.custom_add',
                   'sku.image_slot', 'sku.table_image', 'detail.editor',
                   'media.directory_tree', 'media.directory_node'}
    controls = [{'key': item['key'], 'level': item['evidence']['level'], 'source': item['evidence']['source']}
                for item in selectors if item['key'] in active_keys]
    assert {item['key'] for item in controls} == active_keys
    required_source = (SUBPROJECT / 'taobao_publish/required_fields.py').read_text(encoding='utf-8')
    assert "scope:'visible_publish_rows_required',completePage:false" in required_source

    previous_turns = [
        {'evidence': 'E-179..E-182', 'artifact': 'outputs/desktop_required_controls_validation.json',
         'classification': 'progress', 'verified_limit_field': 'live_taobao_filling_executed'},
        {'evidence': 'E-183..E-185', 'artifact': 'outputs/desktop_capture_attributes_validation.json',
         'classification': 'progress', 'verified_limit_field': 'live_taobao_tested'},
        {'evidence': 'E-186..E-188', 'artifact': 'outputs/desktop_media_batch_validation.json',
         'classification': 'progress', 'verified_limit_field': 'live_platform_tested'},
    ]
    for turn in previous_turns:
        evidence = load(turn['artifact'])
        assert evidence[turn['verified_limit_field']] is False
        turn['same_blocking_condition_present'] = True

    requirements = [
        requirement('shared_frontend', '淘宝/抖音共用编辑、SKU、上传入口和进度，不新增专用固定区或设置向导',
            '当前前端源码、79组隔离交互、运行静态页面标记',
            ['tauri-app/src/views/ProductManager.vue', 'tests/frontend_publish_flow.cjs', 'outputs/desktop_click_browser_runtime.json'],
            '当前商品在真实平台完整交互尚未验证；共同组件与调用路由已验证'),
        requirement('account_browser', '平台随账户绑定，启动或复用隔离浏览器并保持登录',
            '真实Flask函数隔离回归及冻结启动/并发保护核对',
            ['../src/shop_session.py', '../tests/test_shop_platform_api.py', 'outputs/desktop_click_browser_build.json'],
            '当前淘宝账户的实际浏览器、登录与后续导航没有本轮现场证据'),
        requirement('category_and_brand', '搜索发品、匹配类目、默认无品牌并进入下一步',
            '本地原生类目模型与下一步/品牌回读反例',
            ['tests/test_category_first_pipeline.py', 'tests/test_default_brand_and_media_content.py'],
            '当前页面的类目候选、品牌控件和跳转仍需现场确认'),
        requirement('media_directories', '进入商品父目录及主图/SKU/详情子目录，高效查找与上传',
            '隔离目录树、原生文件输入、批量队列和整批图库查询',
            ['taobao_publish/media_library.py', 'tests/test_media_directory_flow.py', 'tests/test_media_batch_lookup.py'],
            '当前目录树或文件夹卡片形态、点击方式、上传目的地和云端文件夹创建/合并规则未验证'),
        requirement('main_images', '主图完整上传、按要求位置和顺序入位',
            '5个主图位置、部分缓存及内容身份的隔离联跑',
            ['outputs/media_batch_five_main_handoff.json', 'tests/test_media_batch_lookup.py'],
            '真实上传服务与当前页面主图入位、顺序核对尚未验证'),
        requirement('sku_names_images', '完整销售规格及各自SKU图准确对应',
            '当前候选配置的原生规格输入、按身份匹配行和图片回读',
            ['taobao_publish/form_adapters.py', 'tests/test_runtime_native_controls.py'],
            '当前淘宝自定义模式、规格行及图片入口是否符合支持结构未验证'),
        requirement('prices_stock_titles', '用户编辑的标题、售价和库存准确传到平台并回读',
            '版本绑定、真实本地SQLite/HTTP保存、逐行值与标题边界回归',
            ['../tests/test_product_save_snapshot.py', 'tests/test_media_stage_integrity.py'],
            '当前表格控件与平台实际约束仍需相应真实验证'),
        requirement('captured_facts', '采集资料可支撑必填填写，不编造缺失商品事实',
            '明确来源的属性存储、版本绑定、五类必填属性精确匹配',
            ['taobao_publish/captured_attributes.py', 'taobao_publish/attribute_fill.py', 'outputs/captured_attribute_pipeline_handoff.json'],
            '当前商品实际可用参数未知；旧记录没有自动补造参数；复合材质/资质尚需真实事实与控件'),
        requirement('all_required_and_logistics', '填写平台全部必填项及物流信息',
            '已识别的可见必填控件检查；运费模板取明确值或当前页已选项',
            ['taobao_publish/required_fields.py', 'taobao_publish/stages.py'],
            '完整必填清单、折叠/动态区段、复合控件及店铺物流真实选项缺失', 'incomplete'),
        requirement('detail_editor', '详情图片按顺序写入实际编辑器并回读',
            '原生HTML编辑区的隔离填写与内容核对',
            ['taobao_publish/form_adapters.py', 'tests/test_runtime_native_controls.py'],
            '当前编辑器形态未验证，iframe或私有编辑器尚无已确认适配'),
        requirement('failure_cancel_reporting', '隔离并发、明确失败、取消和如实报告结果',
            '相关安全回归、进度/结果共同前端79组隔离验证',
            ['../tests/test_sidecar_upload_safety.py', 'tests/frontend_publish_flow.cjs'],
            '真实平台取消及异常恢复表现未验证；不得以100%替代整页必填证明'),
        requirement('stop_before_submit', '本次淘宝只填写，停在提交前，不保存草稿或提交',
            '授权门、冻结代码和模型零草稿/提交记录',
            ['taobao_publish/authorization.py', 'outputs/media_batch_five_main_handoff.json'],
            '本地约束已验证；真实提交前整页填写验收仍未完成'),
        requirement('real_publication', '最终稳定发布及平台成功结果核对',
            '只有提交授权门及明确未实证的提交处理器',
            ['taobao_publish/stages.py'],
            '先完成提交前真实验收，实际提交还需要用户明确授权；本轮不以此为当前填写阻塞原因', 'deferred_by_user_scope'),
    ]
    # 保存关联源码的指纹，避免未来把这次审查套到已变化的代码上。
    paths = ['taobao_publish/media_library.py', 'taobao_publish/page.py', 'taobao_publish/stages.py',
             'taobao_publish/required_fields.py', 'taobao_publish/verification.py',
             'taobao_publish/attribute_fill.py', 'contracts/selectors.json']
    output = {
        'checked_at': datetime.now().astimezone().isoformat(),
        'scope': 'full original objective; local source, package, runtime and isolated evidence only',
        'goal_completion_proven': False,
        'recommended_goal_status': 'blocked',
        'previous_goal_turn_classification': 'progress',
        'same_blocker_consecutive_preceding_goal_turns_confirmed': 3,
        'preceding_turns': previous_turns,
        'blocking_condition': '当前淘宝工作台及完整必填事实无法由现有工具合法读取；核心剩余适配与真实验收需要新的页面或商品事实',
        'static_candidate_level_is_not_itself_a_blocker': True,
        'known_agent_validation_jobs_waiting': [],
        'user_platform_task_list_read': False,
        'application_kept_running': True,
        'runtime_sha256': runtime['sha256'],
        'local_health_success': runtime['health_success'],
        'local_deployment_matches_build': runtime['release_backend_matches_build'],
        'current_regression': validation['package_regression'],
        'active_runtime_controls_needing_current_platform_evidence': controls,
        'archived_page_images': sorted(path.name for path in (SUBPROJECT/'captures').glob('*.png')),
        'production_required_reader': {'scope': 'visible_publish_rows_required', 'completePage': False},
        'requirements': requirements,
        'source_sha256': {name: hashlib.sha256((SUBPROJECT/name).read_bytes()).hexdigest() for name in paths},
        'next_needed_evidence': ['用户提供更新版本实际停点/错误文字及相应去敏控件资料',
                                 '或工具访问策略明确允许的当前淘宝执行环境'],
        'live_platform_actions_performed': False,
        'original_objective_preserved': True,
    }
    assert_clean(output)
    target = SUBPROJECT / 'outputs/goal_full_scope_reaudit_20261005.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'requirements': len(requirements), 'completion_proven': False,
                      'same_blocker_preceding_turns': 3, 'recommended_goal_status': 'blocked',
                      'runtime_healthy': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
