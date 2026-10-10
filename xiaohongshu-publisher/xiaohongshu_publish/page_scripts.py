# -*- coding: utf-8 -*-
"""小红书千帆：页面表达式（真机验证过的写法，集中一处，便于复用与审查）。

每条表达式都对应 `docs/05-证据日志.md` 里一条 `verified` 条目；
改动前先读 `AGENTS.md` 的四条实现纪律。
"""

from __future__ import annotations

import json

#: 抽屉/遮罩可见数量——第四条纪律的判据（开着就点不到页面控件）
DRAWER_STATE = """(() => {
  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  return {drawers:Array.from(document.querySelectorAll('[class*="material-space-drawer"]')).filter(visible).length,
          masks:Array.from(document.querySelectorAll('[class*="d-drawer-mask"]')).filter(visible).length,
          visibility:document.visibilityState};
})()"""

#: 关抽屉：只能点**抽屉自己的**「取消」（点遮罩、Esc 实测都关不掉）
DRAWER_CANCEL = """(() => {
  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const drawer=Array.from(document.querySelectorAll('[class*="material-space-drawer"]')).filter(visible)[0];
  if(!drawer) return {found:false, reason:'drawer_not_open'};
  const hits=Array.from(drawer.querySelectorAll('button,[class*="d-button"]')).filter(visible)
    .filter(e=>(e.textContent||'').trim()==='取消');
  if(!hits.length) return {found:false, reason:'cancel_not_found'};
  const r=hits[0].getBoundingClientRect();
  return {found:true, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2)};
})()"""

#: 点击前反查命中（第三条纪律）：返回最上层元素，调用方自行判断是否就是目标
HIT_TEST = """(() => {
  const el=document.elementFromPoint(X, Y);
  if(!el) return {found:false};
  const chain=[]; let n=el, depth=0;
  while(n && depth<4){ chain.push(n.tagName.toLowerCase()+(n.className?'.'+String(n.className).split(/\\s+/).slice(0,2).join('.'):'')); n=n.parentElement; depth++; }
  const r=el.getBoundingClientRect();
  return {found:true, tag:el.tagName.toLowerCase(), cls:String(el.className||'').slice(0,60),
          text:(el.textContent||'').trim().slice(0,20), chain,
          rect:{x:Math.round(r.x), y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)}};
})()"""

#: 标题框定位：可见 input[type=text] 中 placeholder 提到「品牌」的那个
#: （轮换提示与顶部帮助框都不能当锚点，见证据日志 E-XHS-TITLE-INPUT-PINNED）
FIND_TITLE = """(() => {
  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const inputs=Array.from(document.querySelectorAll('input[type="text"]')).filter(visible);
  const el=inputs.find(e=>/品牌/.test(e.placeholder||''));
  if(!el) return {found:false, placeholders:inputs.map(e=>(e.placeholder||'').slice(0,22))};
  const r=el.getBoundingClientRect();
  return {found:true, x:Math.round(r.x+r.width/2), y:Math.round(r.y+r.height/2),
          value:el.value||''};
})()"""

#: 填标题：**只能**用原生 setter + input/change（第二条纪律），并主动失焦触发类目区块
SET_TITLE_TEMPLATE = """(() => {
  const visible=e=>{const r=e.getBoundingClientRect();const s=getComputedStyle(e);
    return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const inputs=Array.from(document.querySelectorAll('input[type="text"]')).filter(visible);
  const el=inputs.find(e=>/品牌/.test(e.placeholder||''));
  if(!el) return {ok:false, reason:'title_input_not_found'};
  const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  el.focus();
  setter.call(el, TEXT);
  el.dispatchEvent(new Event('input', {bubbles:true}));
  el.dispatchEvent(new Event('change', {bubbles:true}));
  el.blur();
  el.dispatchEvent(new Event('blur', {bubbles:true}));
  return {ok:true, value:el.value, length:(el.value||'').length};
})()"""

#: 页面状态：标题计数器 / 类目区块 / 平台报错
READ_STATE = """(() => {
  const body=document.body.innerText||'';
  const lines=body.split('\\n').map(t=>t.trim()).filter(Boolean);
  const m=body.match(/\\d+\\/60/);
  return {url:location.href, title_counter:m? m[0] : '',
          category_lines:lines.filter(t=>/类目|品类|识别|未开通/.test(t)&&t.length<=50).slice(0,12),
          errors:lines.filter(t=>/错误|请选择|请填写|必填|不能为空/.test(t)&&t.length<=46).slice(0,8)};
})()"""


def set_title_script(title: str) -> str:
    """生成"填标题"表达式（JSON 转义，避免中文/引号注入）。"""
    return SET_TITLE_TEMPLATE.replace("TEXT", json.dumps(title, ensure_ascii=False))


def hit_test_script(x: int, y: int) -> str:
    """生成"反查命中"表达式。"""
    return HIT_TEST.replace("X", str(int(x))).replace("Y", str(int(y)))
