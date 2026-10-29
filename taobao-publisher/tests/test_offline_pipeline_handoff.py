"""真实保存→HTTP创建→工作线程→流水线→本地模型DOM；不触碰运行应用或平台。

淘宝接口与 worker 来自真实的 ``src/sidecar/taobao_routes.py`` / ``taobao_service.py``（2026-10-20 起；以前是按名字从 app.py
里抽三个函数 exec）；保存商品仍是 app.py 里的 ``save_info``（由 ``test_product_save_snapshot.save_case`` 抽出来）。
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
from types import SimpleNamespace

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from test_product_save_snapshot import save_case
from test_candidate_form_adapters import browser, fixture_contracts

from src.sidecar.taobao_routes import create_taobao_blueprint
from src.sidecar.taobao_service import TaobaoPublishService
from taobao_publish import pipeline, stages, page, form_adapters
from taobao_publish.constants import STAGE_ORDER
from taobao_publish.preflight import PageSnapshot


@pytest.fixture
def handoff(save_case, browser, fixture_contracts, monkeypatch, tmp_path):
    """只替换平台边界；真实保存、HTTP任务和工作线程共用同一个隔离记录。"""
    product = tmp_path / '模型商品'
    directories = ('主图/800', 'SKU', '详情页')
    for directory in directories:
        (product / directory).mkdir(parents=True)
    main = product / '主图/800/主图01.jpg'
    Image.new('RGB', (800, 800), 'white').save(main)
    contents = []
    for index, name in enumerate(['黑色-白色【5双装】+均码(35-40)【甄选优质棉】', '燕麦-咖啡【5双装】+均码(35-40)【甄选优质棉】']):
        image = product / 'SKU' / ('规格%s.jpg' % index)
        Image.new('RGB', (800, 800), (50 + index * 90, 80, 100)).save(image)
        contents.append({'path': str(image), 'name': name, 'price': 20.8 + index * 9})
    for index in range(2):
        Image.new('RGB', (800, 800), (80, 40 + index * 90, 30)).save(product / '详情页' / ('详情%s.jpg' % index))
    save_case.db.update(path=str(product), content=json.dumps(contents, ensure_ascii=False), shipping_template='抖店旧模板')
    ns = save_case.ns
    ns['traceback'] = traceback
    save_case.app.config['TESTING'] = True
    ns['datetime'] = datetime
    # 真实的淘宝发布服务：数据目录在临时目录里；启动日志被调用就是出了意外，直接让用例失败。
    # 账户门禁只换掉「平台校验」「当前账户」「切换互斥」三个问句，账户锁仍是真实的那把。
    accounts = SimpleNamespace(
        with_lock=save_case.guard.with_lock, lock=save_case.guard.lock,
        require_publish_platform=ns['_require_publish_platform'],
        active_account=lambda: {'profile_name': '测试账户', 'platform': 'taobao'},
        account_change_blocked=lambda: None,
    )
    service = TaobaoPublishService(
        record_model=ns['Record'], repo_root=str(ROOT), accounts=accounts, shop_service=None,
        normalize_debug_address=lambda value: value, resolve_data_file=lambda name: tmp_path / 'runtime' / name,
        bootstrap_log=lambda message: (_ for _ in ()).throw(AssertionError(message)),
    )
    ns['taobao_service'] = service        # 保存商品的编辑保护读的是同一份任务表
    launch_calls = []
    service.ensure_fill_browser = lambda: launch_calls.append('local_model_only') or 'http://127.0.0.1:1/json/list'
    # 此夹具专门覆盖旧发布页上传模型；目录先行在 test_folder_import_flow 中独立验证。
    # 必须替换工厂边界，禁止连接任何真实应用/浏览器端口。
    from taobao_publish import folder_import
    monkeypatch.setattr(folder_import, 'make_preparer', lambda *args: None)
    monkeypatch.setenv('TAOBAO_MEDIA_ROUTE', 'dom')
    actual_from_record = pipeline.run_from_record
    service.load_pipeline = lambda: SimpleNamespace(run_from_record=lambda row, request, **options:
        actual_from_record(row, request, contracts=fixture_contracts, **options))
    save_case.app.register_blueprint(create_taobao_blueprint(
        service=service, accounts=accounts, record_model=ns['Record'], resolve_data_file=lambda name: tmp_path / 'runtime' / name,
        require_product_revision=ns['_require_product_revision'],
    ))

    def session(ctx):
        # 虚拟URL只作检查器测试数据；浏览器始终是 file: 本地模型，未进行此URL导航。
        ctx.scratch['snapshot'] = PageSnapshot(url='https://item.upload.taobao.com/sell/ai/category.htm',
            title='LOCAL_MODEL_ONLY', has_workbench_root=True, has_category_page=True,
            has_blocking_overlay=False, has_submit_control=True, has_save_draft_control=True)
        return stages.StageOutcome(summary='模型会话边界（不读取真实浏览器或账户）')
    def category(ctx):
        ctx.scratch['select_category'] = {'category_id': '900000001', 'scope': 'local_model_only'}
        return stages.StageOutcome(summary='模型类目导航边界（未访问淘宝）')
    monkeypatch.setitem(stages.STAGE_HANDLERS, 'session', replace(stages.STAGE_HANDLERS['session'], run=session))
    monkeypatch.setitem(stages.STAGE_HANDLERS, 'select_category', replace(stages.STAGE_HANDLERS['select_category'], run=category))
    monkeypatch.setattr(page, 'open_media_popup', lambda client, **options:
        form_adapters._checked(client, page.build_open_media_popup_expression()))
    uploads = []
    cancel_on_upload = {'value': False}
    def upload(client, files, *, context_id, rename_to, expected_sha256=None):
        for name in rename_to:
            url = 'https://img.example.invalid/' + name
            client.evaluate('addCard(%s,%s); window.uploadCalls++' % (json.dumps(name), json.dumps(url)))
            uploads.append(name)
        if cancel_on_upload['value']:
            for task in service.tasks.values():
                task['cancelled'] = True
        return {'ok': True, 'confirmed': rename_to, 'landed': rename_to}
    monkeypatch.setattr(page, 'upload_files_to_media', upload)
    return SimpleNamespace(case=save_case, browser=browser, contents=contents, launch_calls=launch_calls,
                           uploads=uploads, cancel_on_upload=cancel_on_upload, service=service)


def save_and_start(handoff, stale=False, props=None):
    edit = {'_id': 7, 'title': '阶段联跑标题', 'remark': '', 'repo': 100, 'clazz': 2, 'attr_size': 2,
            'for_publish': True, 'platform': 'taobao', 'account_profile': '测试账户'}
    for index, sku in enumerate(handoff.contents, 1):
        for key, value in {'path': sku['path'], 'name': sku['name'], 'price': sku['price']}.items():
            edit['attr_%s_%s' % (key, index)] = value
    saved = handoff.case.client.post('/save_info', json=edit)
    assert saved.status_code == 200 and saved.json['success'] is True
    revision = saved.json['data']['record_revision']
    if stale:
        handoff.case.db['title'] = '保存后另一次编辑'
    product = {'title': edit['title'], 'category_keyword': '中筒袜', 'sku_mode': 'custom',
               'skus': [{'spec_values': {'颜色分类': sku['name']}, 'image_path': sku['path'],
                         'price': sku['price'], 'stock': 100} for sku in handoff.contents]}
    if props is not None:
        product['props'] = props
    started = handoff.case.client.post('/api/taobao/publish/start', json={
        'record_id': 7, 'platform': 'taobao', 'account_profile': '测试账户', 'fill_only': True,
        'dry_run': False, 'stop_before_submit': True, 'product': product, 'expected_record_revision': revision})
    if stale:
        return started, None
    assert started.status_code == 200 and started.json['success'] is True, started.json
    task_id = started.json['data']['task_id']
    deadline = time.monotonic() + 20
    while handoff.service.tasks[task_id]['status'] in ('pending', 'running'):
        if time.monotonic() >= deadline:
            raise AssertionError('本地模型任务未在限定时间内结束')
        time.sleep(0.02)
    return started, deepcopy(handoff.service.tasks[task_id])


def test_real_http_worker_pipeline_handoff_in_local_browser(handoff):
    _, task = save_and_start(handoff)
    _dbg = os.environ.get("TAOBAO_DEBUG_DETAIL_ROW")
    if _dbg:
        # 一次性诊断：把「宝贝详情」行的真实 DOM 状态写成 ASCII 转义文件
        _probe = handoff.browser.evaluate(
            '(()=>{const vis=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);'
            'return r.width>0&&r.height>0&&s.visibility!=="hidden"&&s.display!=="none";};'
            'const tx=el=>(el.innerText||el.textContent||"").replace(/\\s+/g," ").trim();'
            'const out=[];for(const row of document.querySelectorAll(".sell-component-info-wrapper-wrap")){'
            'const l=row.querySelector(".sell-component-info-wrapper-label");if(!l)continue;'
            'if(tx(l).replace(/[*＊\\s]/g,"")!=="宝贝详情")continue;const r=row.getBoundingClientRect();'
            'const eds=Array.from(row.querySelectorAll("[contenteditable=\'true\'],textarea"));'
            'out.push({vis:vis(row),w:Math.round(r.width),h:Math.round(r.height),'
            'sd:getComputedStyle(row).display,pd:row.parentElement?getComputedStyle(row.parentElement).display:null,'
            'edN:eds.length,eds:eds.map(e=>({tag:e.tagName,vis:vis(e),vlen:String(e.value||"").length,'
            'hlen:String(e.innerHTML||"").length,imgs:(e.querySelectorAll?e.querySelectorAll("img").length:0),'
            'tlen:String(e.textContent||"").replace(/\\s+/g,"").length})),rowImgs:row.querySelectorAll("img[src]").length});}'
            'return out;})()')
        with open(_dbg, "w", encoding="utf-8") as _fh:
            _fh.write(repr(_probe) + "\n")
    assert task['status'] == 'succeeded', task['error']
    assert handoff.launch_calls == ['local_model_only']
    # ⚠️ 阶段数**不要硬编码**（加一个阶段就要回去改一堆测试）。
    # 离线跑到 `readback` 就停（`stopped_before_submit`），所以是 STAGE_ORDER 去掉 submit。
    ran = [step['name'] for step in task['steps']]
    assert ran == [name for name in STAGE_ORDER if name != 'submit'], ran
    assert task['progress'] == 100
    assert all(step['status'] in ('ok', 'skipped') for step in task['steps'])
    assert len(handoff.uploads) == 5
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0
    result = task['result']
    assert result['success'] is True and result['stopped_before_submit'] is True
    assert result['data']['form_verification']['status'] == 'partial'
    assert result['data']['form_verification']['complete'] is False
    assert '整页必填尚未确认' in task['message']
    assert page.read_freight_template(handoff.browser) == '模型商家默认模板'
    assert '抖店旧模板' not in json.dumps(result, ensure_ascii=False)
    rows = page.read_sku_row_numbers(handoff.browser)
    assert rows[0]['specs'] == [handoff.contents[1]['name']]
    assert rows[0]['price'] == '29.80' and rows[1]['price'] == '20.80'
    from taobao_publish.sanitize import assert_clean
    artifact = {'scope': 'local_synthetic_browser_only', 'live_platform_tested': False,
                'platform_boundaries_simulated': ['session', 'category_navigation', 'image_upload_server'],
                'test_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'message': task['message'], 'result': result, 'submitted_or_saved_draft': False}
    assert_clean(artifact)
    (ROOT / 'taobao-publisher/outputs/phase_offline_pipeline_handoff.json').write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def test_changed_version_is_rejected_before_browser_or_worker(handoff):
    response, task = save_and_start(handoff, stale=True)
    assert response.status_code == 409 and task is None
    assert not handoff.launch_calls and not handoff.uploads


def test_actual_required_value_missing_fails_at_final_readback(handoff):
    # ⚠️ 不能再用「把品牌置空」来构造这个场景：流水线的 `fill_props` 阶段**会自己去写品牌**
    # （这正是它该做的事），置空会在写阶段被填回来，于是回读合理地通过。
    #
    # 要测的是「**页面上的必填值没填** → 回读必须失败」，所以用一个
    # **流水线不会去填的必填行**：追加一个未选中的「发货时间」单选组。
    # （「发货时间」是平台必填项，但当前流水线不接管它——它该由人/后续阶段负责。）
    handoff.browser.evaluate(
        'document.body.insertAdjacentHTML("beforeend",'
        '"<div class=\\"sell-component-info-wrapper-wrap\\">'
        '<div class=\\"sell-component-info-wrapper-label-wrap\\">'
        '<span>*</span><span class=\\"sell-component-info-wrapper-label\\">发货时间</span></div>'
        '<input type=radio name=delivery><input type=radio name=delivery></div>")')
    _, task = save_and_start(handoff)
    assert task['status'] == 'failed', task
    assert task['result']['stage'] == 'readback'
    assert not task['result']['data']['form_verification']['complete']
    assert any(blocker.get('field') == '发货时间' for blocker in task['blockers'])
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0


def test_cancel_after_upload_preserves_stage_boundary_and_does_not_submit(handoff):
    handoff.cancel_on_upload['value'] = True
    _, task = save_and_start(handoff)
    assert task['status'] == 'cancelled', task
    assert task['result']['error']['code'] == 'CANCELLED'
    assert not task['result']['data']['form_verification']['complete']
    assert any(step['status'] == 'cancelled' for step in task['steps'])
    assert handoff.browser.evaluate('window.submitCalls + window.draftCalls') == 0
