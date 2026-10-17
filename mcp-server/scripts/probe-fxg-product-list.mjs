// 只读：把 9500 的标签页导航到「商品列表」，读出前 N 条商品标题与状态，
// 用于核对是否因为 11:42 / 11:44 两次成功提交而产生了重复铺货。
//
// 只做 Page.navigate（GET）+ Runtime.evaluate 读取，不点击、不编辑、不下架。
//
// 用法：node mcp-server/scripts/probe-fxg-product-list.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const LIST_URL = process.env.LIST_URL || "https://fxg.jinritemai.com/ffa/g/list";
const PORT = process.env.CDP_PORT || "9500";

process.env.DOUYIN_CDP_LIST_URL = `http://127.0.0.1:${PORT}/json/list`;

const READ = `(() => {
  const norm = (s) => String(s || '').replace(/\\s+/g, ' ').trim();
  const lines = [];
  const body = document.body ? norm(document.body.innerText) : '';
  lines.push('URL=' + location.href.split('?')[0]);
  lines.push('HEAD=' + body.slice(0, 160));

  // 商品列表行：优先找 table 的 tbody tr；否则按含「商品」的卡片块兜底
  const rows = Array.from(document.querySelectorAll('tbody tr'));
  lines.push('TABLE_ROWS=' + rows.length);
  rows.slice(0, 15).forEach((tr, i) => {
    const t = norm(tr.innerText || '');
    if (t) lines.push('  r[' + i + '] ' + t.slice(0, 150));
  });
  if (!rows.length) {
    // 兜底：抓页面里所有像商品标题的链接文本
    const links = Array.from(document.querySelectorAll('a'))
      .map((a) => norm(a.innerText || ''))
      .filter((t) => t.length >= 12 && t.length <= 80);
    lines.push('LINK_TEXTS=' + links.length);
    links.slice(0, 20).forEach((t, i) => lines.push('  l[' + i + '] ' + t));
  }
  // 「共 N 件商品」之类的计数
  const m = body.match(/共\\s*(\\d+)\\s*[件个]/);
  lines.push('TOTAL_HINT=' + (m ? m[1] : '?'));
  return lines.join('\\n');
})()`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page");
console.error(`# 目标数 ${pages.length}`);
if (!pages.length) process.exit(0);

const t = pages[0];
const client = new CdpClient(t.webSocketDebuggerUrl);
try {
  await client.connect();
  await client.call("Page.enable").catch(() => {});
  await client.call("Runtime.enable").catch(() => {});
  console.error(`# 导航到 ${LIST_URL}`);
  await client.call("Page.navigate", { url: LIST_URL }).catch((e) => console.error("  navigate 失败:", e.message));
  await delay(9000);
  const res = await Promise.race([
    client.call("Runtime.evaluate", { expression: READ, returnByValue: true, awaitPromise: true }),
    delay(20000).then(() => { throw new Error("timeout"); }),
  ]);
  console.log(res.exceptionDetails
    ? '  JS 抛错: ' + (res.exceptionDetails.exception?.description || res.exceptionDetails.text)
    : res.result.value);
} finally {
  client.close();
}
