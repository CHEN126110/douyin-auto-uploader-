# -*- coding: utf-8 -*-
"""骨架占位闸门：「内容在、渲染没完」（cards=0 且 skel>0）不是空目录终态。

2026-10-08 run17/run20 真机根因：选图器为每个待渲染项摆一个可见的
``<i class="PicList_i_dom__…">`` 占位图标；目录拉取悬挂时它与空占位一起出现
（cards=0 empty=1 skel=N），旧终态判据把它当成「空目录」放行，随后按 ID
选图必报 missing。恢复：点**别的**目录再点回来强制重拉（点当前节点平台
不重新拉取）。
"""
import itertools
import time
from unittest.mock import Mock

import pytest

from test_candidate_form_adapters import browser, item  # noqa: F401
from test_media_directory_flow import install_tree
from taobao_publish import media_library, page


def _client(states):
    """按序返回列表状态的假 client；最后一条无限重复。"""
    client = Mock()
    seq = itertools.chain(states, itertools.repeat(states[-1]))
    client.evaluate = Mock(side_effect=lambda *args, **kwargs: next(seq))
    return client


def _no_busy(monkeypatch):
    monkeypatch.setattr(page, 'read_media_gallery_state',
                        lambda client, **kwargs: {'busy': False})


def test_skeleton_is_not_a_terminal_empty_folder(monkeypatch):
    _no_busy(monkeypatch)
    client = _client([{'cards': 0, 'empty': 1, 'skel': 5, 'sig': ''}])
    with pytest.raises(page.PageError):
        media_library.wait_listing_settled(client, context_id=None, timeout=0.5)


def test_true_empty_folder_without_skeleton_is_terminal(monkeypatch):
    _no_busy(monkeypatch)
    client = _client([{'cards': 0, 'empty': 1, 'skel': 0, 'sig': ''}])
    state = media_library.wait_listing_settled(client, context_id=None, timeout=1.0)
    assert state['cards'] == 0 and state['empty'] == 1


def test_transient_skeleton_waits_for_hydration(monkeypatch):
    _no_busy(monkeypatch)
    client = _client([
        {'cards': 0, 'empty': 1, 'skel': 5, 'sig': ''},
        {'cards': 0, 'empty': 1, 'skel': 5, 'sig': ''},
        {'cards': 2, 'empty': 0, 'skel': 0, 'sig': 'a|b'},
        {'cards': 2, 'empty': 0, 'skel': 0, 'sig': 'a|b'},
    ])
    state = media_library.wait_listing_settled(client, context_id=None, timeout=2.0)
    assert state['cards'] == 2


def test_retrigger_clicks_away_then_back(monkeypatch):
    monkeypatch.setattr(media_library, 'read_directory', lambda client, **kwargs: {
        'supported': True,
        'paths': [['全部图片'], ['全部图片', '123'], ['全部图片', '123', '主图'], ['全部图片', '123', 'SKU']],
        'path': ['全部图片', '123', '主图'],
    })
    monkeypatch.setattr(media_library, 'wait_listing_settled', lambda client, **kwargs: {'cards': 2})
    client = Mock()
    client.evaluate = Mock(return_value={'ok': True, 'supported': True})
    target = ['全部图片', '123', '主图']
    assert media_library.retrigger_listing(client, target, context_id=None) is True
    # 点击走 folder_expression(action='open')（路径后缀匹配、只点 own-label）；
    # 其余 evaluate 调用是点击前的列表签名采样。
    clicks = [str(call) for call in client.evaluate.call_args_list
              if '"action": "open"' in str(call)]
    assert len(clicks) == 2
    # 第一次点的是「别的」目录（不是目标），第二次点回目标。
    assert '主图' not in clicks[0]
    assert '主图' in clicks[1]


def test_retrigger_without_any_other_node_is_an_honest_failure(monkeypatch):
    monkeypatch.setattr(media_library, 'read_directory', lambda client, **kwargs: {
        'supported': True, 'paths': [['全部图片', '123', '主图']], 'path': ['全部图片', '123', '主图'],
    })
    client = Mock()
    assert media_library.retrigger_listing(client, ['全部图片', '123', '主图'], context_id=None) is False
    client.evaluate.assert_not_called()


#: 夹具复现 run20：第一次进主图目录渲染成骨架占位卡住（卡片不水合），
#: 之后的进入才渲染真卡片——open_directory 必须等超时后自动「点走再点回」恢复。
SKELETON_ONCE_JS = '''window.skelArmed=true;
  window.cardsByFolder={'主图':[{name:'m1.jpg',url:'https://img.example.invalid/m1.jpg'},
    {name:'m2.jpg',url:'https://img.example.invalid/m2.jpg'}]};
  window.renderFolder=()=>{
    const gallery=document.getElementById('gallery');gallery.replaceChildren();
    if(window.currentFolder==='主图'&&window.skelArmed){
      const area=document.createElement('div');area.className='PicList_main-emptyarea';
      for(let i=0;i<5;i++){const tile=document.createElement('i');tile.className='PicList_i_dom__test';
        tile.style.cssText='display:inline-block;width:96px;height:96px';area.append(tile);}
      gallery.append(area);window.skelArmed=false;return;
    }
    const rows=window.cardsByFolder[window.currentFolder]||[];
    if(!rows.length){const e=document.createElement('div');e.className='next-empty';e.textContent='暂无图片';gallery.append(e);return;}
    for(const row of rows)window.addCard(row.name,row.url);
  };'''


def test_open_directory_recovers_from_stuck_skeleton(browser):
    install_tree(browser)
    browser.evaluate(SKELETON_ONCE_JS)
    path = media_library.open_directory(browser, ['全部图片', '123', '主图'], context_id=None)
    assert path == ['全部图片', '123', '主图']
    clicks = browser.evaluate('window.directoryClicks')
    # 恢复路径：点过别的目录（离开主图），再点回主图。
    assert clicks.count('主图') >= 2
    assert any(label not in ('123', '主图') for label in clicks[clicks.index('主图'):])
    state = browser.evaluate(media_library._LISTING_STATE_EXPRESSION)
    assert state['cards'] == 2 and state['skel'] == 0


#: 夹具复现 run21：点目录后**旧目录的卡片迟滞约 700ms 才被清空重渲**（真机
#: 后台标签页定时器节流的表现，run12 同款）。「内容变过一次」判据要求点击前
#: 签名与采样签名同形构造——run21 根因就是给采样签名加 skel 字段时漏改点击前
#: 签名（三元组 vs 四元组逐字比较永不相等），判据在旧卡片第一帧就直接成立，
#: open_directory 带着上一目录的卡片放行，随后按 ID 选主图报 missing。
LAZY_CLEAR_TREE_JS = '''window.directoryClicks=[];
  const tree=document.createElement('div');tree.setAttribute('role','tree');
  tree.style.cssText='display:block;width:250px';document.body.prepend(tree);
  window.cardsByFolder={
    'SKU':[{name:'s1.jpg',url:'https://img.example.invalid/s1.jpg'},
           {name:'s2.jpg',url:'https://img.example.invalid/s2.jpg'},
           {name:'s3.jpg',url:'https://img.example.invalid/s3.jpg'}],
    '主图':[{name:'m1.jpg',url:'https://img.example.invalid/m1.jpg'},
            {name:'m2.jpg',url:'https://img.example.invalid/m2.jpg'}]};
  window.renderFolder=()=>{
    const gallery=document.getElementById('gallery');gallery.replaceChildren();
    for(const row of window.cardsByFolder[window.currentFolder]||[])window.addCard(row.name,row.url);
  };
  function node(label,parent){const li=document.createElement('div');li.setAttribute('role','treeitem');
    li.setAttribute('aria-label',label);li.style.cssText='min-height:28px;width:200px';
    const text=document.createElement('span');text.className='next-tree-node-label';text.textContent=label;li.append(text);
    text.onclick=e=>{e.stopPropagation();tree.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));
      li.setAttribute('aria-selected','true');window.directoryClicks.push(label);window.currentFolder=label;
      setTimeout(()=>window.renderFolder(),700);};parent.append(li);return li;}
  const root=node('全部图片',tree),product=node('123',root);
  node('主图',product);const sku=node('SKU',product);node('详情页',product);
  openGallery(null,document.querySelector('#mainImages .sell-component-material-item-view'));
  sku.setAttribute('aria-selected','true');window.currentFolder='SKU';window.renderFolder();'''


def test_open_directory_waits_out_stale_previous_folder_cards(browser):
    browser.evaluate(LAZY_CLEAR_TREE_JS)
    path = media_library.open_directory(browser, ['全部图片', '123', '主图'], context_id=None)
    assert path == ['全部图片', '123', '主图']
    # 返回的那一刻列表必须**已经是主图的卡片**；迟滞窗口内放行会拿到 SKU 的旧卡片。
    state = browser.evaluate(media_library._LISTING_STATE_EXPRESSION)
    assert state['cards'] == 2, '返回时列表仍是上一目录（SKU）的旧卡片：变化判据失效'
    assert 'm1.jpg' in state['sig'] and 's1.jpg' not in state['sig']


#: 真机选图器的树节点是**双层**的：``li[role=treeitem] > div.next-tree-node >
#: span.next-tree-node-label``（2026-10-08 run23 探针实测 26 节点 = 13 目录 × 2）。
#: 旧点击表达式同时匹配两种选择器，每个目录名都命中两个节点、恒判
#: directory_ambiguous——骨架恢复在真机上一次都没执行过。上面的 install_tree
#: 夹具只有单层节点，复现不了；本夹具按真机双层结构搭。点击语义也对齐真机：
#: **点已选中的节点是 no-op**（平台不重新拉取），否则夹具里「点当前节点」
#: 会假装修复成功，run26 的假空缺陷就测不出来。
DOUBLE_LAYER_TREE_JS = '''window.directoryClicks=[];
  const tree=document.createElement('div');tree.setAttribute('role','tree');
  tree.style.cssText='display:block;width:250px';document.body.prepend(tree);
  window.cardsByFolder={
    'SKU':[{name:'s1.jpg',url:'https://img.example.invalid/s1.jpg'}],
    '主图':[{name:'m1.jpg',url:'https://img.example.invalid/m1.jpg'},
            {name:'m2.jpg',url:'https://img.example.invalid/m2.jpg'}]};
  window.skelArmed=true;
  window.renderFolder=()=>{
    const gallery=document.getElementById('gallery');gallery.replaceChildren();
    if(window.currentFolder==='主图'&&window.skelArmed){
      const area=document.createElement('div');area.className='PicList_main-emptyarea';
      for(let i=0;i<5;i++){const t=document.createElement('i');t.className='PicList_i_dom__x';
        t.style.cssText='display:inline-block;width:96px;height:96px';area.append(t);}
      gallery.append(area);window.skelArmed=false;return;}
    for(const row of window.cardsByFolder[window.currentFolder]||[])window.addCard(row.name,row.url);
  };
  function node(label,parent){const li=document.createElement('div');li.setAttribute('role','treeitem');
    li.setAttribute('aria-label',label);li.style.cssText='min-height:28px;width:200px';
    const inner=document.createElement('div');inner.className='next-tree-node';
    const text=document.createElement('span');text.className='next-tree-node-label';text.textContent=label;
    inner.append(text);li.append(inner);parent.append(li);
    text.onclick=e=>{e.stopPropagation();
      if(li.getAttribute('aria-selected')==='true')return;
      tree.querySelectorAll('[aria-selected]').forEach(n=>n.removeAttribute('aria-selected'));
      li.setAttribute('aria-selected','true');window.directoryClicks.push(label);window.currentFolder=label;
      document.getElementById('gallery').replaceChildren();setTimeout(()=>window.renderFolder(),120);};return li;}
  const root=node('全部图片',tree),product=node('123',root);
  node('主图',product);node('SKU',product);node('详情页',product);
  openGallery(null,document.querySelector('#mainImages .sell-component-material-item-view'));
  root.setAttribute('aria-selected','true');window.currentFolder='全部图片';'''


def test_retrigger_works_on_double_layer_tree(browser):
    """run23 回归：双层节点树下骨架恢复必须真的点出去再点回来。"""
    browser.evaluate(DOUBLE_LAYER_TREE_JS)
    path = media_library.open_directory(browser, ['全部图片', '123', '主图'], context_id=None)
    assert path == ['全部图片', '123', '主图']
    clicks = browser.evaluate('window.directoryClicks')
    # 第一次进主图卡住 → 点去 SKU（别的目录）→ 再点回主图。
    assert clicks == ['主图', 'SKU', '主图'], clicks
    state = browser.evaluate(media_library._LISTING_STATE_EXPRESSION)
    assert state['cards'] == 2 and state['skel'] == 0


#: 假空版双层树夹具：主图第一次进入渲染成**空占位**（empty=1 且 skel=0——
#: 合法终态的形状，但目录里其实有 2 张图；2026-10-08 run26 真机就是这个形态，
#: 探针实测：假空挂在主图上几分钟，点 SKU 再点回 0.5 秒水合 10 张）。
FAKE_EMPTY_TREE_JS = DOUBLE_LAYER_TREE_JS.replace(
    'window.skelArmed=true;', 'window.emptyArmed=true;').replace(
    """if(window.currentFolder==='主图'&&window.skelArmed){
      const area=document.createElement('div');area.className='PicList_main-emptyarea';
      for(let i=0;i<5;i++){const t=document.createElement('i');t.className='PicList_i_dom__x';
        t.style.cssText='display:inline-block;width:96px;height:96px';area.append(t);}
      gallery.append(area);window.skelArmed=false;return;}""",
    """if(window.currentFolder==='主图'&&window.emptyArmed){
      const area=document.createElement('div');area.className='PicList_main-emptyarea';
      area.style.cssText='display:block;width:200px;height:120px';
      gallery.append(area);window.emptyArmed=false;return;}""")


def test_requery_recovers_from_fake_empty_folder(browser):
    """run26 回归：假空目录下 requery 必须走「点走再点回」。

    点已选中的当前节点平台不重新拉取，而假空又是合法终态——refresh_gallery
    会按「刷新成功」放行，重选依旧 missing；只有点走再点回能强制重拉。
    """
    browser.evaluate(FAKE_EMPTY_TREE_JS)
    result = browser.evaluate(
        media_library.folder_expression(['全部图片', '123', '主图'], action='open'))
    assert result.get('ok') is True
    time.sleep(0.4)  # 夹具点击后 120ms 渲染；等假空占位出来
    state = browser.evaluate(media_library._LISTING_STATE_EXPRESSION)
    assert state['cards'] == 0 and state['empty'] == 1 and state['skel'] == 0
    # 夹具 addCard：checkbox.value = 文件名里的数字左补 10 位 → m1/m2。
    media_library.pick_media_by_id_with_requery(
        browser, ['0000000001', '0000000002'], context_id=None, wait=1.0)
    assert browser.evaluate('window.selectCalls') == 2, '两张主图都必须被点中'
    clicks = browser.evaluate('window.directoryClicks')
    assert clicks == ['主图', 'SKU', '主图'], clicks
