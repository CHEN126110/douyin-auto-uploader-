// 只读：把当前发布页的**网络耗时**取出来，用于给「等 AI 生成」这类超时定实测依据。
//
// 为什么能读到历史：浏览器 performance 计时在页面生命周期内是持久的 ——
// 即使 AI 早就生成完了，当时那些请求的 startTime / duration 仍然在。
//
// 红线：只做 Runtime.evaluate 读取，不点击、不输入、不上传、不保存、不提交。
//
// 用法：
//   $env:DOUYIN_CDP_LIST_URL='http://127.0.0.1:9502/json/list'
//   node mcp-server/scripts/probe-publish-network-timings.mjs
import { getCdpTargets, CdpClient, delay } from "../cdp-client.js";

const URL_FILTER = process.env.URL_FILTER || "/ffa/g/create";
const TOP_N = Number(process.env.TOP_N || "25");

// 只返回扁平字符串：该页面给 JSON.stringify 装了 polyfill，返回对象会踩到循环引用。
const TIMING_JS = `
(function(){
  const norm = function (s) { return String(s || '').replace(/\\s+/g, ' ').trim(); };
  const lines = [];
  const nav = performance.getEntriesByType('navigation')[0];
  if (nav) {
    lines.push('NAV domContentLoaded=' + Math.round(nav.domContentLoadedEventEnd)
      + 'ms load=' + Math.round(nav.loadEventEnd)
      + 'ms duration=' + Math.round(nav.duration) + 'ms');
  }
  const res = performance.getEntriesByType('resource') || [];
  const rows = [];
  for (let i = 0; i < res.length; i++) {
    const r = res[i];
    const name = String(r.name || '');
    if (!/jinritemai|fxg|\\/product\\/|\\/ffa\\//i.test(name)) continue;
    rows.push({ n: name, s: Math.round(r.startTime), d: Math.round(r.duration), t: r.initiatorType });
  }
  lines.push('RES count=' + rows.length);
  rows.sort(function (a, b) { return b.d - a.d; });
  const top = rows.slice(0, ${TOP_N});
  for (let i = 0; i < top.length; i++) {
    const r = top[i];
    const short = r.n.replace(/^https?:\\/\\/[^/]+/, '').slice(0, 110);
    lines.push('  +' + r.s + 'ms  ' + r.d + 'ms  ' + r.t + '  ' + short);
  }
  // AI 生成相关接口单独点名（便于确认「等的是哪个请求」）
  const ai = rows.filter(function (r) { return /ai|smart|assist|generate|schema|product/i.test(r.n); });
  ai.sort(function (a, b) { return b.d - a.d; });
  lines.push('AI_LIKE count=' + ai.length);
  for (let i = 0; i < Math.min(ai.length, 12); i++) {
    const r = ai[i];
    const short = r.n.replace(/^https?:\\/\\/[^/]+/, '').slice(0, 110);
    lines.push('  +' + r.s + 'ms  ' + r.d + 'ms  ' + short);
  }
  const now = Math.round(performance.now());
  lines.push('NOW=' + now + 'ms');
  return lines.join('\\n');
})()
`;

const targets = await getCdpTargets();
const pages = targets.filter((t) => t.type === "page" && String(t.url || "").includes(URL_FILTER));
console.error(`# 命中 ${pages.length} 个目标(过滤 ${URL_FILTER})`);

for (const t of pages) {
  const client = new CdpClient(t.webSocketDebuggerUrl);
  try {
    await client.connect();
    await client.call("Runtime.enable").catch(() => {});
    const res = await Promise.race([
      client.call("Runtime.evaluate", { expression: TIMING_JS, returnByValue: true, awaitPromise: true }),
      delay(20000).then(() => { throw new Error("timeout"); }),
    ]);
    console.log(`\n=== ${t.url} ===`);
    if (res.exceptionDetails) {
      console.log("  JS 抛错: " + (res.exceptionDetails.exception?.description || res.exceptionDetails.text));
    } else {
      console.log(res.result.value);
    }
  } catch (e) {
    console.log(`\n=== ${t.url} ===\n  失败: ${e instanceof Error ? e.message : String(e)}`);
  } finally {
    client.close();
  }
}
