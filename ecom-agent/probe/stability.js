#!/usr/bin/env node
/**
 * 稳定性探针 —— 「现在能用」不等于「一直能用」。
 *
 * ── 与可行性探针的区别 ──────────────────────────────────────
 * `feasibility.js` 回答「这个能力存不存在」，是一次性的。
 * 本文件回答「它能不能被稳定依赖」，**必须长期重复跑才有意义**。
 *
 * 用户的原话：「现在可以用，那么后续不一定可以稳定使用。」
 *
 * 已经踩到的不稳定：
 *   - 反爬码 10001010A「当前环境存在风险」—— 密集调用后触发，重试无用
 *   - st=100704「服务器错误」—— 刷新会话可恢复，但会中断流程
 *   - 同一端点在不同时段返回行数不同（热点榜 5 / 50，取决于参数）
 *
 * ── 测四件事 ────────────────────────────────────────────────
 *   1. 可用率      重复调用的成功比例
 *   2. 值一致性    已定稿窗口的数据，多次调用应当完全相同
 *   3. 结构指纹    字段路径与类型的哈希，平台改版会让它变
 *   4. 延迟分布    p50 / max，用于判断超时该设多少
 *
 * ── 不做什么 ────────────────────────────────────────────────
 * **默认不压测。** 密集调用会触发反爬，把正常业务也一起拖下水。
 * 要探限流阈值请显式 `--stress`，并且知道自己在做什么。
 *
 * ── 用法 ────────────────────────────────────────────────────
 *   node probe/stability.js                 默认每个端点 3 次
 *   node probe/stability.js --repeat 5      指定重复次数
 *   node probe/stability.js --stress        探限流阈值（会触发风控，慎用）
 *   node probe/stability.js --report        只看历史累积结果，不发起调用
 *
 * 结果累积在 probe/stability_history.jsonl，跨次运行比对趋势。
 */
'use strict';

const path = require('path');
const fs = require('fs');
const crypto = require('crypto');

const DATA_REPO = process.env.DOUDIAN_REPO || 'D:\\抖店';
const HISTORY = path.join(__dirname, 'stability_history.jsonl');

/** 被观测的端点。只放决策链路真正依赖的，不是全部 73 个。 */
const WATCHED = [
  { toolId: 'compass.search.industry_rank', why: 'N1 需求信号——机会模型的主输入' },
  { toolId: 'compass.market.index_range', why: 'N1 进入门槛——供需比的替代方案' },
  { toolId: 'diagnosis.compass.hot_sale_rank', why: 'N1 供给侧——竞争强度' },
  { toolId: 'diagnosis.compass.video_after_watch', why: 'N1 内容侧归因（名不副实，实为热点榜）' },
  { toolId: 'diagnosis.compass.product_rank', why: 'N11/N12 闭环验证——没它就不是闭环' },
];

function loadDataLayer() {
  try {
    return {
      dispatcher: require(path.join(DATA_REPO, 'lib', 'dispatcher.js')),
      compassTools: require(path.join(DATA_REPO, 'lib', 'compass_tools.js')),
    };
  } catch (e) {
    console.error(`无法加载数据层 ${DATA_REPO}：${e.message}`);
    process.exit(2);
  }
}

/**
 * 结构指纹：字段路径 + 类型，不含值。
 *
 * 平台改版时字段增删改名，指纹会变而值可能照常有——
 * 这正是解析器静默失效的时刻，光看「有没有数据」发现不了。
 */
function schemaFingerprint(obj, depth = 0, prefix = '') {
  const paths = [];
  const walk = (v, p, d) => {
    if (d > 5 || v === null || v === undefined) return;
    if (Array.isArray(v)) {
      // 数组只看第一个元素的形状，长度不进指纹（行数本来就会变）
      if (v.length) walk(v[0], p + '[]', d + 1);
      return;
    }
    if (typeof v === 'object') {
      for (const k of Object.keys(v).sort()) {
        // 元数据键不进指纹：它们是我们自己加的，不反映平台结构
        if (k === '_meta' || k === '_unwrapped' || k === '_reason' || k === '_empty') continue;
        walk(v[k], p ? `${p}.${k}` : k, d + 1);
      }
      return;
    }
    paths.push(`${p}:${typeof v}`);
  };
  walk(obj, prefix, depth);
  paths.sort();
  return crypto.createHash('sha256').update(paths.join('\n')).digest('hex').slice(0, 16);
}

/**
 * 值指纹：只对已定稿窗口有意义——同一天多次调用应当完全一致。
 *
 * ⚠️ 必须先剔除**天然易变但无业务含义**的东西，否则会误报。
 * 实测踩过：`qr_code` 等图片 URL 的 CDN 域名在 p3/p11/p26.douyinpic.com
 * 之间轮换，导致同一份数据算出 3 个不同指纹。
 * 一个会对 CDN 轮换报警的稳定性探针，只会让人学会忽略它的警报。
 */
function valueFingerprint(obj) {
  // URL 只保留路径：CDN 域名轮换是负载均衡，不是数据变化。
  // 三种形式都要覆盖——只处理 https:// 会漏掉协议相对写法与 JSON 里的转义写法，
  // 漏一种就残留误报（实测热点榜就是被漏掉的那种形式坑了一次）。
  // 用字符串构造正则，避免多层转义把它写坏（这里已经因为转义踩过两次）。
  // 只归一化**主机名**，路径原样保留——路径变了是真的变了。
  const HOST = '[A-Za-z0-9._-]+\\.(?:com|cn|net|org)';
  const CDN_PATTERNS = [
    new RegExp('https?:(?:\\\\?/){2}' + HOST, 'g'),   // https://host 与 JSON 里的 https:\/\/host
    new RegExp('(^|[^:A-Za-z0-9])(?:\\\\?/){2}' + HOST, 'g'), // //host 协议相对
  ];
  const normalizeUrl = (str) => CDN_PATTERNS.reduce(
    (acc, re, i) => acc.replace(re, i === 0 ? '<cdn>' : '$1<cdn>'), str);
  const strip = (v, d = 0) => {
    if (v === null || v === undefined) return v;
    if (typeof v === 'string') return normalizeUrl(v);
    if (typeof v !== 'object') return v;
    // 深度不设上限：易变字段藏在第 7 层以下时，限深会让指纹把整棵子树
    // 原样带进去，反而更容易误报（实测就是这么发现 qr_code 的）
    if (d > 40) return '<深度截断>';
    if (Array.isArray(v)) return v.map((x) => strip(x, d + 1));
    const out = {};
    for (const k of Object.keys(v).sort()) {
      // _meta 之类是我们自己加的，含 shopId/rows 会随调用变
      if (k.startsWith('_')) continue;
      out[k] = strip(v[k], d + 1);
    }
    return out;
  };
  return crypto.createHash('sha256').update(JSON.stringify(strip(obj))).digest('hex').slice(0, 16);
}

function classifyError(res) {
  const msg = String((res && res.error && res.error.message) || res.summary || '');
  const code = String((res && res.error && res.error.apiCode) || '');
  if (/10001010A|环境存在风险/.test(msg + code)) return { kind: 'ANTI_BOT', note: '反爬风控——重试无用，需换环境或等冷却' };
  if (/100704|服务器错误/.test(msg + code)) return { kind: 'TRANSIENT', note: '平台瞬时错误——刷新会话可恢复' };
  if (/11001|网络不稳定/.test(msg + code)) return { kind: 'RATE_LIMIT', note: '限流' };
  if (/登录|LOGIN|鉴权/.test(msg)) return { kind: 'AUTH', note: '登录态失效' };
  if (/参数/.test(msg)) return { kind: 'PARAM', note: '参数校验失败——通常是我们的问题不是平台的' };
  return { kind: 'OTHER', note: msg.slice(0, 60) };
}

async function measure(D, toolId, repeat) {
  const samples = [];
  for (let i = 0; i < repeat; i++) {
    const t0 = Date.now();
    let res;
    try { res = await D.call(toolId, {}); } catch (e) { res = { success: false, error: { message: e.message } }; }
    const ms = Date.now() - t0;
    if (res && res.success) {
      samples.push({ ok: true, ms, schema: schemaFingerprint(res.data), value: valueFingerprint(res.data) });
    } else {
      samples.push({ ok: true === false, ms, err: classifyError(res) });
    }
  }

  const ok = samples.filter((s) => s.ok);
  const lat = samples.map((s) => s.ms).sort((a, b) => a - b);
  const schemas = new Set(ok.map((s) => s.schema));
  const values = new Set(ok.map((s) => s.value));
  const errs = {};
  samples.filter((s) => !s.ok).forEach((s) => { errs[s.err.kind] = (errs[s.err.kind] || 0) + 1; });

  return {
    toolId,
    attempts: repeat,
    successes: ok.length,
    availability: ok.length / repeat,
    latencyP50: lat[Math.floor(lat.length / 2)],
    latencyMax: lat[lat.length - 1],
    schemaCount: schemas.size,
    schema: [...schemas][0] || null,
    valueCount: values.size,
    // 已定稿窗口多次调用值应当一致。不一致说明数据未定稿或有采样。
    valueStable: ok.length > 1 ? values.size === 1 : null,
    errors: errs,
    errorNotes: [...new Set(samples.filter((s) => !s.ok).map((s) => s.err.note))],
  };
}

/** 压测：连续调用直到出错，找出限流阈值。**会触发风控，默认不跑。** */
async function stress(D, toolId, cap = 30) {
  console.log(`\n⚠️  压测 ${toolId}（最多 ${cap} 次，会触发风控）`);
  for (let i = 1; i <= cap; i++) {
    let res;
    try { res = await D.call(toolId, {}); } catch (e) { res = { success: false, error: { message: e.message } }; }
    if (!res || !res.success) {
      const c = classifyError(res);
      console.log(`   第 ${i} 次失败：${c.kind} — ${c.note}`);
      return { toolId, failedAt: i, kind: c.kind };
    }
    process.stdout.write(`   ${i}`);
  }
  console.log(`\n   ${cap} 次全部成功，未触发限流`);
  return { toolId, failedAt: null, survived: cap };
}

function readHistory() {
  if (!fs.existsSync(HISTORY)) return [];
  return fs.readFileSync(HISTORY, 'utf8').split('\n').filter(Boolean)
    .map((l) => { try { return JSON.parse(l); } catch (_) { return null; } })
    .filter(Boolean);
}

function report(history) {
  if (!history.length) {
    console.log('还没有历史记录。跑一次 `node probe/stability.js` 开始积累。');
    console.log('稳定性需要多次、跨时段的观测才有意义——单次结果说明不了问题。');
    return;
  }
  const runs = [...new Set(history.map((h) => h.runAt))].sort();
  console.log(`历史累积 ${runs.length} 轮观测：${runs[0].slice(0, 16)} → ${runs[runs.length - 1].slice(0, 16)}`);
  console.log('');

  const byTool = {};
  for (const h of history) {
    (byTool[h.toolId] = byTool[h.toolId] || []).push(h);
  }
  console.log('端点'.padEnd(40) + '轮次  累计可用率  结构指纹');
  console.log('─'.repeat(78));
  for (const [tool, hs] of Object.entries(byTool)) {
    const att = hs.reduce((n, h) => n + h.attempts, 0);
    const suc = hs.reduce((n, h) => n + h.successes, 0);
    const schemas = [...new Set(hs.map((h) => h.schema).filter(Boolean))];
    const drift = schemas.length > 1 ? `⚠️ 变过 ${schemas.length} 次` : (schemas[0] ? '稳定' : '—');
    console.log(tool.padEnd(40) + String(hs.length).padStart(3)
      + String(Math.round((suc / att) * 100) + '%').padStart(11) + '   ' + drift);
  }

  const drifted = Object.entries(byTool)
    .filter(([, hs]) => [...new Set(hs.map((h) => h.schema).filter(Boolean))].length > 1);
  if (drifted.length) {
    console.log('');
    console.log('⚠️ 结构指纹变过的端点——平台可能改版，解析器需要复核：');
    drifted.forEach(([t]) => console.log(`   ${t}`));
  }
}

async function main() {
  const argv = process.argv.slice(2);
  const history = readHistory();

  if (argv.includes('--report')) { report(history); return; }

  const repeat = Number((argv.find((a) => a.startsWith('--repeat')) || '').split(/[= ]/)[1])
    || (argv.includes('--repeat') ? Number(argv[argv.indexOf('--repeat') + 1]) : 0)
    || 3;

  const L = loadDataLayer();
  const runAt = new Date().toISOString();
  const results = [];

  console.log(`稳定性观测（每个端点 ${repeat} 次）`);
  console.log('');
  for (const w of WATCHED) {
    const m = await measure(L.dispatcher, w.toolId, repeat);
    results.push({ runAt, why: w.why, ...m });
    const icon = m.availability === 1 ? '✅' : m.availability >= 0.5 ? '⚠️ ' : '❌';
    console.log(`${icon} ${w.toolId}`);
    console.log(`   可用 ${m.successes}/${m.attempts}   延迟 p50=${m.latencyP50}ms max=${m.latencyMax}ms`);
    if (m.valueStable === false) {
      console.log(`   ⚠️ 值不一致：${m.valueCount} 种不同结果——已定稿窗口不该如此，`
        + '说明数据未定稿或有采样，基于它的结论不可复现');
    }
    if (m.schemaCount > 1) console.log(`   ⚠️ 结构不一致：${m.schemaCount} 种`);
    m.errorNotes.forEach((n) => console.log(`   ✗ ${n}`));
  }

  if (argv.includes('--stress')) {
    const target = WATCHED[0].toolId;
    const s = await stress(L.dispatcher, target);
    results.push({ runAt, stress: s });
  }

  fs.appendFileSync(HISTORY, results.map((r) => JSON.stringify(r)).join('\n') + '\n');
  try { await L.compassTools.close(); } catch (_) { /* ignore */ }

  console.log('');
  console.log('='.repeat(78));
  const all = results.filter((r) => r.attempts);
  const avail = all.reduce((n, r) => n + r.availability, 0) / (all.length || 1);
  console.log(`本轮平均可用率 ${(avail * 100).toFixed(0)}%   已记入 ${path.basename(HISTORY)}`);
  console.log('');
  console.log('单次观测说明不了稳定性。建议按天重复跑，然后 `--report` 看趋势。');
}

main();
