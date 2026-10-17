// 只读：把 AI 生成表单里「产品材质面料」这一块的 DOM 结构读出来。
// 目的是给「逐行材质编辑器」写填充逻辑（经典表单那套 aurora 弹层在这里不存在）。
//
// 红线：只做 Runtime.evaluate 读取，不点击、不输入、不保存、不提交。
//
// 用法：
//   $env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9502/json/list'
//   node mcp-server/scripts/probe-ai-material-dom.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const URL_FILTER = process.env.URL_FILTER || "/ffa/g/create";

const PROBE = `(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const vis = (n) => !!n && n.nodeType === 1 && (n.offsetParent || n.getClientRects().length > 0);
  const lines = [];

  // 1) 用「添加材质」按钮定位编辑器（比标题稳：标题在侧栏「填写助手」里也会出现）
  const addBtnsAll = Array.from(document.querySelectorAll('button,span,div'))
    .filter((n) => vis(n) && norm(n.innerText || n.textContent) === '添加材质');
  lines.push('ADD_MATERIAL_BTNS=' + addBtnsAll.length);
  if (!addBtnsAll.length) {
    const body = document.body ? norm(document.body.innerText) : '';
    lines.push('NO_ADD_BTN HEAD=' + body.slice(0, 300));
    return lines.join('\\n');
  }
  const addBtn = addBtnsAll[0];
  let container = addBtn;
  for (let i = 0; i < 8 && container.parentElement; i++) {
    container = container.parentElement;
    if (container.querySelectorAll('input').length > 0) break;
  }
  const titleEl = null;
  lines.push('CONTAINER_TAG=' + container.tagName.toLowerCase()
    + ' cls=' + String(container.className || '').slice(0, 90));

  // 2) 行：按「删除」按钮分组
  const delBtns = Array.from(container.querySelectorAll('button,span,div'))
    .filter((n) => vis(n) && norm(n.innerText || n.textContent) === '删除');
  lines.push('DELETE_BTNS=' + delBtns.length);

  // 3) 容器内所有 input
  const inputs = Array.from(container.querySelectorAll('input'));
  lines.push('INPUTS=' + inputs.length);
  inputs.forEach((inp, i) => {
    const attrs = ['type', 'placeholder', 'class', 'value', 'role', 'aria-label', 'maxlength']
      .map((a) => (inp.getAttribute(a) ? a + '=' + String(inp.getAttribute(a)).slice(0, 50) : ''))
      .filter(Boolean).join(' ');
    lines.push('  in[' + i + '] ' + attrs + ' | visible=' + vis(inp));
  });

  // 4) 每个「下拉」候选：带 select 类名的元素
  const sels = Array.from(container.querySelectorAll('[class*="select"],[class*="Select"],[role="combobox"]'));
  lines.push('SELECT_LIKE=' + sels.length);
  sels.slice(0, 12).forEach((el, i) => {
    const r = el.getBoundingClientRect();
    lines.push('  sel[' + i + '] ' + el.tagName.toLowerCase()
      + ' cls=' + String(el.className || '').slice(0, 70)
      + ' text=' + norm(el.innerText || '').slice(0, 30)
      + ' rect=' + [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)].join(','));
  });

  // 5) 关键按钮
  for (const label of ['添加材质', '删除', '清空']) {
    const hits = Array.from(container.querySelectorAll('button,span,div'))
      .filter((n) => vis(n) && norm(n.innerText || n.textContent) === label);
    if (!hits.length) { lines.push('BTN ' + label + ' = 0'); continue; }
    const el = hits[0];
    lines.push('BTN ' + label + ' = ' + hits.length
      + ' | tag=' + el.tagName.toLowerCase()
      + ' cls=' + String(el.className || '').slice(0, 80));
  }

  // 6) 每行读到的「材质名 + 百分比」
  const text = norm(container.innerText || '');
  lines.push('SECTION_TEXT=' + text.slice(0, 260));
  return lines.join('\\n');
})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes(URL_FILTER));
console.error(`# 命中 ${pages.length} 个目标`);

for (const t of pages) {
  const client = new CdpClient(t.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const res = await Promise.race([
      client.call("Runtime.evaluate", { expression: PROBE, returnByValue: true, awaitPromise: true }),
      delay(20000).then(() => { throw new Error("timeout"); }),
    ]);
    console.log(`\n=== ${t.url} ===`);
    console.log(res.exceptionDetails
      ? '  JS 抛错: ' + (res.exceptionDetails.exception?.description || res.exceptionDetails.text)
      : res.result.value);
  } catch (e) {
    console.log(`\n=== ${t.url} ===\n  失败: ${e instanceof Error ? e.message : String(e)}`);
  } finally {
    client.close();
  }
}
