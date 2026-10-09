# -*- coding: utf-8 -*-
"""仅连接新建的隔离 headless 浏览器及本地人工页面；禁止外部网络和账户复用。"""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request
from unittest.mock import Mock

from PIL import Image
import pytest

from taobao_publish import form_adapters as adapters, page, stages
from taobao_publish.authorization import WriteAuthorization
from taobao_publish.contracts import load_contracts, SelectorContract
from taobao_publish.models import ImageSet, PublishItem, SkuEntry


@pytest.fixture
def fixture_contracts():
    contracts = load_contracts()
    payload = deepcopy(contracts.selectors._payload)
    keys = set(adapters.CUSTOM_KEYS + adapters.SKU_IMAGE_KEYS + adapters.DETAIL_KEYS)
    for entry in payload['selectors']:
        if entry['key'] in keys:
            entry['evidence'] = {'level': 'verified', 'source': 'LOCAL_SYNTHETIC_FIXTURE_ONLY'}
    return replace(contracts, selectors=SelectorContract(payload))


@pytest.fixture
def item(tmp_path):
    files = []
    for index in range(4):
        path = tmp_path / ('测试素材_%s.jpg' % index)
        Image.new('RGB', (800, 800), (index * 50, 30, 50)).save(path)
        files.append(str(path))
    return PublishItem(record_id=19, record_name='仅本地模型', title='真实模型袜子', sku_mode='custom',
        skus=[SkuEntry(spec_values={'颜色分类': '黑色-白色【5双装】+均码(35-40)【甄选优质棉】'},
                       image_path=files[0], price=29.8, stock=100),
              SkuEntry(spec_values={'颜色分类': '燕麦-咖啡【5双装】+均码(35-40)【甄选优质棉】'},
                       image_path=files[1], price=39.8, stock=80)],
        images=ImageSet(sku=files[:2], detail=files[2:]))


@pytest.fixture
def browser(tmp_path, monkeypatch, request):
    runtime_root = Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright'
    executables = sorted(runtime_root.glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'))
    if not executables:
        pytest.skip('缺少本地独立 headless Chromium；其余纯离线守卫测试仍运行')
    profile = tmp_path / 'isolated-browser-profile'
    source = Path(__file__).parent / 'fixtures/candidate-form.html'
    local_http = getattr(request, 'param', None) == 'memory_http_only'
    resolver = '--host-resolver-rules=MAP * ~NOTFOUND' + (', EXCLUDE 127.0.0.1' if local_http else '')
    process = subprocess.Popen([str(executables[-1]), '--headless', '--remote-debugging-port=0',
        '--user-data-dir=' + str(profile), '--disable-background-networking', '--no-proxy-server',
        resolver, '--disable-component-update', '--no-first-run', source.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    client = None
    try:
        active = profile / 'DevToolsActivePort'
        deadline = time.monotonic() + 15
        while not active.is_file():
            if time.monotonic() > deadline or process.poll() is not None:
                raise RuntimeError('隔离测试浏览器启动失败')
            time.sleep(0.1)
        port = int(active.read_text(encoding='utf-8').splitlines()[0])
        with urllib.request.urlopen('http://127.0.0.1:%s/json/list' % port, timeout=5) as response:
            targets = json.load(response)
        matches = [target for target in targets if target.get('url') == source.as_uri()]
        assert len(matches) == 1, '只能连接此次新建浏览器中的明确本地模型文件'
        client = page.PageClient.connect(matches[0]['webSocketDebuggerUrl'], target_url=source.as_uri())
        if local_http:
            # 仅目录Entry研究使用自建临时HTTP；仍禁止请求现有应用、插件和浏览器端口。
            forbidden = {1420, 5001, 8769, 9222, 9333, 9334} | set(range(9500, 9600))
            client.send('Network.enable')
            client.send('Network.setBlockedURLs', {'urls': [
                '*://127.0.0.1:%s/*' % port for port in sorted(forbidden)]})
        deadline = time.monotonic() + 5
        while client.evaluate('location.href') != source.as_uri() or client.evaluate('document.readyState') != 'complete':
            if time.monotonic() >= deadline:
                raise RuntimeError('本地模型页面没有完成加载')
            time.sleep(0.05)
        assert client.evaluate('location.protocol') == 'file:'
        monkeypatch.setattr(page, 'open_sku_drawer', lambda c: adapters._checked(c, page.build_open_sku_drawer_expression()))
        monkeypatch.setattr(page, 'confirm_sku_creation', lambda c: adapters._checked(c, page.build_confirm_sku_expression()))
        monkeypatch.setattr(page, 'wait_for_sku_table', lambda c, **kwargs: page.read_sku_table(c))
        monkeypatch.setattr(page, 'media_iframe_context', lambda c: None)
        monkeypatch.setattr(page, 'close_media_popup', lambda c, **kwargs: c.evaluate("closeGallery()"))
        monkeypatch.setattr(stages, '_open_publish_page', lambda ctx, **kwargs: client)
        # 阶段关闭连接按正常语义发生；此测试复用连接完成多阶段回读，最后由夹具关闭。
        monkeypatch.setattr(client, 'close', lambda: None)
        yield client
    finally:
        if client is not None:
            client.ws.close()
        # 只结束此 Popen 对应的隔离测试进程树，不操作用户 Chrome 或桌面应用。
        import psutil
        if process.poll() is None:
            children = psutil.Process(process.pid).children(recursive=True)
            process.terminate()
            for child in children:
                try:
                    child.terminate()
                except psutil.NoSuchProcess:
                    pass
            process.wait(timeout=8)


def prepare_in_fixture(browser, item, contracts, monkeypatch):
    browser.evaluate("openGallery(null,null)")
    def upload(client, files, *, context_id, rename_to, expected_sha256=None):
        for name in rename_to:
            url = 'https://img.example.invalid/' + name + '?version=' + 'x' * 220
            client.evaluate('addCard(%s,%s); window.uploadCalls++' % (json.dumps(name), json.dumps(url)))
        return {'ok': True, 'confirmed': rename_to, 'landed': rename_to}
    monkeypatch.setattr(page, 'upload_files_to_media', upload)
    receipts = adapters.prepare_media(browser, item, contracts, context_id=None)
    browser.evaluate("closeGallery()")
    # ⚠️ **给回执补上 `picture_id`**：真实平台的回执带 `object.fileId`，而卡片
    # `checkbox.value` 就是它——按 ID 选图靠这个。夹具若不给，就必须退回"按名字找"
    # 那条旧路，测试也就覆盖不到生产实际走的分支。
    # 值与夹具 `addCard` 取同一个来源：文件名里的数字。
    for role in receipts.values():
        for receipt in role:
            digits = ''.join(ch for ch in str(receipt.get('name') or '') if ch.isdigit())
            # 与夹具 addCard 的 checkbox.value 同源：数字不足 10 位左补零
            # （选图表达式只采信 10 位以上数字串形态的图片 ID）。
            receipt.setdefault('picture_id', (digits or '1').zfill(10))
    return receipts


def test_missing_required_selector_contract_does_not_open_a_page(item, monkeypatch):
    opener = Mock(side_effect=AssertionError('未定义控件不能打开店铺页面'))
    monkeypatch.setattr(stages, '_open_publish_page', opener)
    contracts = load_contracts()
    payload = json.loads(json.dumps(contracts.selectors._payload))
    payload['selectors'] = [entry for entry in payload['selectors'] if entry['key'] != 'sku.custom_mode']
    ctx = stages.PipelineContext(item=item, dry_run=False, contracts=replace(contracts, selectors=SelectorContract(payload)))
    result = stages.stage_fill_skus(ctx)
    assert not result.ok
    opener.assert_not_called()
    assert [b.field for b in result.blockers] == ['sku.custom_mode']


def test_runtime_guarded_controls_do_not_create_blanket_precheck_blockers(item, monkeypatch):
    from taobao_publish.preflight import PreflightResult
    monkeypatch.setattr(stages, 'run_preflight', lambda *args, **kwargs: PreflightResult(ready=True))
    ctx = stages.PipelineContext(item=item, dry_run=False)
    outcome = stages.stage_precheck(ctx)
    assert outcome.ok and not outcome.blockers
    assert outcome.data['deferred_adapter_blockers'] == {}
    assert stages._stage_adapter_guard(ctx, 'upload_images') is None


def test_orphan_sku_image_is_not_bound_by_array_position(item):
    item.images.sku.append('未关联.jpg')
    with pytest.raises(page.PageError, match='未指定对应'):
        adapters.media_plan(item)


def test_custom_mode_and_media_flow_in_real_local_dom(browser, item, fixture_contracts, monkeypatch):
    receipts = prepare_in_fixture(browser, item, fixture_contracts, monkeypatch)
    assert browser.evaluate('window.uploadCalls') == 4
    assert all(len(receipt['url']) > 120 for role in receipts.values() for receipt in role)
    ctx = stages.PipelineContext(item=item, dry_run=False, contracts=fixture_contracts)
    ctx.scratch['prepared_media'] = receipts
    base = stages.stage_fill_base(ctx)
    assert base.ok, base.summary
    outcome = stages.stage_fill_skus(ctx)
    assert outcome.ok, outcome.summary
    rows = page.read_sku_row_numbers(browser)
    assert rows[0]['specs'] == [item.skus[1].spec_values['颜色分类']]
    assert rows[0]['price'] == '39.80' and rows[0]['stock'] == '80'
    assert rows[1]['price'] == '29.80' and rows[1]['stock'] == '100'
    detail = stages.stage_fill_detail(ctx)
    assert detail.ok, detail.summary
    price_stock = stages.stage_fill_price_stock(ctx)
    assert price_stock.ok, price_stock.summary
    assert not adapters.missing_media_roles(item, ctx.scratch['bound_media'])
    adapters.verify_bound_media(browser, item, fixture_contracts, ctx.scratch['bound_media'])
    final = stages.stage_readback(ctx)
    assert final.ok, final.summary
    assert final.data['required_field_coverage']['completePage'] is False
    assert browser.evaluate('window.submitCalls + window.draftCalls') == 0
    browser.evaluate("document.querySelector('textarea').value=document.querySelector('textarea').value.replace('version=', 'changed=')")
    with pytest.raises(page.FieldMismatchError, match='详情图片'):
        adapters.verify_bound_media(browser, item, fixture_contracts, ctx.scratch['bound_media'])


def test_gallery_duplicate_name_prevents_selection_or_reupload(browser, item, fixture_contracts, monkeypatch):
    receipts = prepare_in_fixture(browser, item, fixture_contracts, monkeypatch)
    receipt = receipts['sku'][0]
    browser.evaluate("openGallery(null,null); document.getElementById('gallery').append(document.getElementById('gallery').firstElementChild.cloneNode(true))")
    uploads = browser.evaluate('window.uploadCalls')
    with pytest.raises(page.PageError, match='ambiguous'):
        adapters.prepare_media(browser, item, fixture_contracts, context_id=None)
    assert browser.evaluate('window.uploadCalls') == uploads


@pytest.mark.parametrize('existing', ['text', 'image', 'video', 'layout'])
def test_unknown_detail_content_is_preserved(browser, item, fixture_contracts, monkeypatch, existing):
    receipts = prepare_in_fixture(browser, item, fixture_contracts, monkeypatch)
    value = {'text': '用户已有说明', 'image': '<img src="https://img.example.invalid/old.jpg">', 'video': '<video></video>', 'layout': '<div class="existing-template"></div>'}[existing]
    browser.evaluate('document.querySelector("textarea").value=' + json.dumps(value))
    with pytest.raises(page.PageError, match='unknown_existing_detail'):
        adapters.fill_detail(browser, item, fixture_contracts, receipts)
    assert browser.evaluate('document.querySelector("textarea").value') == value


def test_contenteditable_and_duplicate_editor_guard(browser, item, fixture_contracts, monkeypatch):
    receipts = prepare_in_fixture(browser, item, fixture_contracts, monkeypatch)
    browser.evaluate("const old=document.querySelector('textarea'); const edit=document.createElement('div'); edit.contentEditable='true';edit.style.cssText='height:200px;width:500px';old.replaceWith(edit)")
    adapters.fill_detail(browser, item, fixture_contracts, receipts)
    config = adapters.config_for(item, fixture_contracts)
    actual = adapters._checked(browser, adapters.build_detail_expression(config))
    assert actual['urls'] == [r['url'] for r in receipts['detail']]
    browser.evaluate("document.querySelector('[contenteditable]').parentElement.append(document.querySelector('[contenteditable]').cloneNode(true))")
    result = browser.evaluate(adapters.build_detail_expression(config, 'write', [r['url'] for r in receipts['detail']]))
    assert result == {'ok': False, 'reason': 'detail_editor_not_unique'}


def test_changed_sku_image_url_fails_final_readback(browser, item, fixture_contracts, monkeypatch):
    receipts = prepare_in_fixture(browser, item, fixture_contracts, monkeypatch)
    _, bindings = adapters.create_custom_skus(browser, item, fixture_contracts, receipts)
    browser.evaluate("document.querySelector('.sku-table-row img').src+='wrong' ")
    with pytest.raises(page.FieldMismatchError, match='SKU 图片'):
        adapters.verify_sku_images(browser, adapters.config_for(item, fixture_contracts), bindings)


def test_disabled_or_standard_input_is_not_written(browser, item, fixture_contracts):
    config = adapters.config_for(item, fixture_contracts)
    browser.evaluate("document.getElementById('drawer').hidden=false;document.querySelector('input[type=radio]').checked=true;document.querySelector('#names input').disabled=true")
    result = browser.evaluate(adapters.build_custom_expression(config, 'name', '中文规格', 0))
    assert not result['ok'] and result['reason'] == 'custom_input_disabled'
    assert browser.evaluate("document.querySelector('#names input').value") == ''
