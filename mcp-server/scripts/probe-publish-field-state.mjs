// Read-only: dump the CURRENT VALUES of the category-attribute fields on every
// FXG publish tab, plus the page-variant signature.
//
// RED LINE: reads DOM only. No navigate / click / upload / save / submit.
//
// Why the output is flat "key=value" lines instead of a JSON object:
//   1. the FXG pages patch JSON.stringify with a polyfill that throws on the
//      circular structures React attaches to DOM nodes;
//   2. any recursive serializer walks into that same cycle and blows the stack.
// Emitting primitives only keeps the whole thing safe and readable.
//
// Usage:
//   $env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9500/json/list'
//   node mcp-server/scripts/probe-publish-field-state.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const URL_FILTER = process.env.URL_FILTER || "/ffa/g/create";

const PROBE = `(() => {
  const norm = function (s) { return String(s == null ? '' : s).replace(/\\s+/g, ' ').trim(); };
  const body = document.body ? (document.body.innerText || '') : '';
  const vis = function (n) { return !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0); };
  const fields = Array.from(document.querySelectorAll('[attr-field-id]'));
  const L = [];
  const put = function (k, v) { L.push(k + ' = ' + norm(v)); };

  put('href', location.href);
  put('title', document.title);
  put('bodyLen', body.length);
  put('fieldCount', fields.length);

  var allIds = [];
  for (var q = 0; q < fields.length; q++) allIds.push(fields[q].getAttribute('attr-field-id'));
  put('allFieldIds', allIds.join(' , '));

  put('marker.aiConfirmCard', /确认信息，继续生成/.test(body));
  put('marker.materialSection', /商品材料/.test(body));
  put('marker.suggestSection', /建议补充/.test(body));
  put('marker.aiEntry202608', /上传资料越完整|下一步，生成商品|任意截图/.test(body));
  put('marker.returnOldText', /返回旧版/.test(body));
  put('marker.returnNewText', /返回新版|体验新版/.test(body));
  put('marker.nextStepText', /下一步/.test(body));
  put('marker.publishBtnText', /发布商品/.test(body));
  put('marker.saveDraftText', /保存草稿/.test(body));
  put('marker.todoSection', /待办/.test(body));

  var tInp = document.querySelector('#pg-title-input');
  put('titleInput.exists', !!tInp);
  put('titleInput.value', tInp ? tInp.value : '');
  put('titleInput.placeholder', tInp ? tInp.getAttribute('placeholder') : '');

  var buttons = [];
  var bs = document.querySelectorAll('button');
  for (var b = 0; b < bs.length; b++) {
    if (!vis(bs[b])) continue;
    var bt = norm(bs[b].innerText);
    if (bt && buttons.indexOf(bt) < 0) buttons.push(bt);
  }
  put('visibleButtons', buttons.slice(0, 45).join(' , '));

  var WANT = ['返回旧版', '返回新版', '体验新版', '下一步', '确认信息，继续生成', '发布商品', '保存草稿', '上一步', '生成商品'];
  var cta = [];
  var cands = document.querySelectorAll('div, span, button, a');
  for (var c = 0; c < cands.length && cta.length < 24; c++) {
    var ct = norm(cands[c].innerText);
    if (ct && WANT.indexOf(ct) >= 0 && vis(cands[c])) {
      var pk = Object.keys(cands[c]).find(function (k) { return k.indexOf('__reactProps$') === 0; });
      var hasHandler = !!(pk && cands[c][pk] && typeof cands[c][pk].onClick === 'function');
      cta.push(ct + ' <' + cands[c].tagName.toLowerCase() + '> cls=' + String(cands[c].className || '').slice(0, 42) + ' handlerSelf=' + hasHandler);
    }
  }
  put('ctaCandidates', cta.join(' ;; '));

  var WATCH = ['面料材质', '筒高', '品牌', '适用性别', '适用人群', '厚度', '图案', '功能', '适用季节', '风格', '商品类目', '类目属性', '商品标题', '材质成分'];
  for (var w = 0; w < WATCH.length; w++) {
    var id = WATCH[w];
    var f = null;
    for (var i = 0; i < fields.length; i++) {
      if (fields[i].getAttribute('attr-field-id') === id) { f = fields[i]; break; }
    }
    if (!f) { put('field[' + id + ']', 'NOT_FOUND'); continue; }
    var tagNodes = f.querySelectorAll('[class*="ecom-g-tag"], [class*="styles_tag"], [class*="tag__"]');
    var tags = [];
    for (var j = 0; j < tagNodes.length && tags.length < 10; j++) {
      var t = norm(tagNodes[j].innerText);
      if (t) tags.push(t);
    }
    var inputs = [];
    var ins = f.querySelectorAll('input, textarea');
    for (var k = 0; k < ins.length && inputs.length < 8; k++) {
      var v = norm(ins[k].value);
      if (v) inputs.push(v);
    }
    var sel = f.querySelector('[class*="selection-item"], [class*="ecom-g-select-selection"], [class*="select-selection"]');
    put('field[' + id + ']',
      'visible=' + vis(f) +
      ' | hasError=' + !!f.querySelector('[class*="error"], [class*="Error"]') +
      ' | tags=[' + tags.join(' ; ') + ']' +
      ' | inputs=[' + inputs.join(' ; ') + ']' +
      ' | selected=' + (sel ? norm(sel.innerText).slice(0, 60) : '') +
      ' | text=' + norm(f.innerText).slice(0, 150));
  }

  var errs = [];
  var es = document.querySelectorAll('[class*="ecom-g-message"], [role="alert"], [class*="toast"]');
  for (var e = 0; e < es.length && errs.length < 8; e++) {
    var et = norm(es[e].innerText);
    if (et && et.length <= 120 && vis(es[e])) errs.push(et);
  }
  put('errors', errs.join(' ;; '));

  // ---- classic-form anchors the automation depends on; do they survive here? ----
  var ANCHORS = {
    'id#saotu': '#saotu',
    'saotu_label_file': '#saotu label input[type=file]',
    'categorySelectorV2': '[class*="categorySelectorV2"]',
    'DragController': '[class*="index_DragController__"]',
    'goodsEditScrollContainer': '[id^="goodsEditScrollContainer"]',
    'pg-title-input': '#pg-title-input',
    'attrfield_商品标题': '[attr-field-id="商品标题"]',
    'attrfield_主图': '[attr-field-id="主图"]',
    'attrfield_主图3:4': '[attr-field-id="主图3:4"]',
    'attrfield_使用品牌名': '[attr-field-id="使用品牌名"]',
    'file_input_any': 'input[type=file]',
    'upload_label_any': 'label input[type=file]',
    'aurora_select_multiple': '[class*="aurora-select-multiple"]',
    'ecom-g-select': '[class*="ecom-g-select"]',
  };
  var anchorOut = [];
  for (var ak in ANCHORS) {
    if (!Object.prototype.hasOwnProperty.call(ANCHORS, ak)) continue;
    var n = document.querySelectorAll(ANCHORS[ak]).length;
    anchorOut.push(ak + '=' + n);
  }
  put('anchors', anchorOut.join(' , '));

  // xpath-only anchors used by app.py
  var XP = {
    next_button_span: '//button[.//span[text()="下一步"]]',
    manual_select: '//span[text()="手动选择"]/..',
    return_old_div: '//div[normalize-space(text())="返回旧版"]',
    return_old_any: '//*[normalize-space(text())="返回旧版"]',
    confirm_generate: '//*[normalize-space(text())="确认信息，继续生成"]',
    publish_span_parent: '//span[text()="发布商品"]/..',
    saotu_xpath: '//div[@id="saotu"]//label[.//input[@type="file"]]',
    mainimg_field: '//div[@attr-field-id="主图"]',
    white_bg: '//div[@attr-field-id="白底图"]',
  };
  var xpOut = [];
  for (var xk in XP) {
    if (!Object.prototype.hasOwnProperty.call(XP, xk)) continue;
    var cnt = -1;
    try {
      cnt = document.evaluate(XP[xk], document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null).snapshotLength;
    } catch (err) { cnt = 'ERR'; }
    xpOut.push(xk + '=' + cnt);
  }
  put('xpaths', xpOut.join(' , '));

  put('headText', norm(body).slice(0, 300));

  return L.join('\\n');
})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes(URL_FILTER));
console.error(`# 命中 ${pages.length} 个目标(过滤 ${URL_FILTER})`);

const results = [];
for (const t of pages) {
  const client = new CdpClient(t.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const res = await Promise.race([
      client.call("Runtime.evaluate", { expression: PROBE, returnByValue: true, awaitPromise: false }),
      delay(15000).then(() => { throw new Error("timeout"); }),
    ]);
    if (res.exceptionDetails) {
      const d = res.exceptionDetails;
      results.push({ targetId: t.id, url: t.url, ok: false, error: (d.exception && (d.exception.description || d.exception.value)) || d.text });
    } else {
      results.push({ targetId: t.id, ok: true, dump: String(res.result.value) });
    }
  } catch (e) {
    results.push({ targetId: t.id, url: t.url, ok: false, error: e instanceof Error ? e.message : String(e) });
  } finally {
    client.close();
  }
}

for (const r of results) {
  console.log("===== target " + r.targetId + " =====");
  if (r.ok) console.log(r.dump);
  else console.log("ERROR: " + r.error);
  console.log("");
}
