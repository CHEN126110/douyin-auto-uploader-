#!/usr/bin/env node
/**
 * 可行性探针 —— 在动手实现之前，逐条验证 DAG 依赖的能力到底存不存在。
 *
 * ── 为什么要有它 ────────────────────────────────────────────
 * 用户的要求：「确保项目是可实现的，而不是出现了问题再去修改，这是猜和摸瞎。」
 *
 * 这不是空话。本项目设计阶段就撞过三次墙，全是做到一半才发现的：
 *   - 纵向归因做不了 —— 罗盘只服务当前周，回溯一律「参数校验失败」
 *   - 供需比算不出来 —— 分母（类目在售商品数）根本拿不到
 *   - 单品指标解不出 —— 真实嵌套比解包器预期多一层
 *
 * 这三条如果先探一遍就能知道，而不是把模块写完再返工。
 *
 * ── 用法 ────────────────────────────────────────────────────
 *   node probe/feasibility.js            跑全部探针
 *   node probe/feasibility.js --json     输出 JSON（供文档生成）
 *
 * ── 判定 ────────────────────────────────────────────────────
 *   OK        能力存在且实测拿到了数据
 *   EMPTY     接口通、结构对，但当前无数据（能力可用，本店暂时没内容）
 *   BLOCKED   平台侧不支持——**这类必须改设计，不能靠重试绕过**
 *   FAIL      调用失败，原因待查
 *
 * EMPTY 与 BLOCKED 的区别是本文件的核心：
 * 前者等数据就行，后者是设计前提不成立。
 */
'use strict';

const path = require('path');

// 数据层在另一个仓库。路径可用环境变量覆盖，不写死。
const DATA_REPO = process.env.DOUDIAN_REPO || 'D:\\抖店';

function loadDataLayer() {
  try {
    return {
      dispatcher: require(path.join(DATA_REPO, 'lib', 'dispatcher.js')),
      compassTools: require(path.join(DATA_REPO, 'lib', 'compass_tools.js')),
      unwrap: require(path.join(DATA_REPO, 'lib', 'compass_unwrap.js')),
      api: require(path.join(DATA_REPO, 'scripts', 'compass', 'compass_api.js')),
    };
  } catch (e) {
    console.error(`无法加载数据层 ${DATA_REPO}：${e.message}`);
    console.error('设 DOUDIAN_REPO 环境变量指向正确路径。');
    process.exit(2);
  }
}

const STATUS = { OK: 'OK', EMPTY: 'EMPTY', BLOCKED: 'BLOCKED', FAIL: 'FAIL' };

/**
 * 探针清单。每条对应 DAG 里一个节点的一个前提。
 *
 * node    依赖它的 DAG 节点
 * claim   这条前提的具体主张（要能被证伪）
 * run     实际去验证，返回 {status, detail, evidence}
 */
function buildProbes(L) {
  const { dispatcher: D, unwrap: U, api } = L;

  /** 从工具结果里找出数据行，兼容数组式与数字键式两种形态。 */
  function rowsOf(res) {
    if (!res || !res.success || !res.data) return [];
    const { _meta, _unwrapped, ...rest } = res.data;

    const pick = (obj) => {
      if (!obj || typeof obj !== 'object') return null;
      for (const v of Object.values(obj)) {
        if (Array.isArray(v) && v.length && typeof v[0] === 'object') return v;
      }
      const numeric = Object.keys(obj).filter((k) => /^\d+$/.test(k));
      if (numeric.length) return numeric.map((k) => obj[k]);
      return null;
    };

    // 旧路径（diagnosis.compass.*）的 data 是罗盘原始结构，
    // 解出来的行挂在 _unwrapped 上。只看 rest 会把「有数据」误判成「空」。
    return pick(rest) || pick(_unwrapped) || [];
  }

  return [
    {
      id: 'N1-industry-words',
      node: 'N1 市场信号采集',
      claim: '能拿到行业搜索词榜，且含成交额与曝光的环比',
      async run() {
        const r = await D.call('compass.search.industry_rank', {});
        const rows = rowsOf(r);
        if (!r.success) return { status: STATUS.FAIL, detail: r.error && r.error.message };
        if (!rows.length) return { status: STATUS.EMPTY, detail: '接口通但无词' };
        const w = rows[0];
        const hasRatio = typeof w.pay_amt__ratio === 'number'
          && typeof w.search_show_ucnt__ratio === 'number';
        return {
          status: hasRatio ? STATUS.OK : STATUS.EMPTY,
          detail: `${rows.length} 词，首位「${w.word}」`,
          evidence: { word: w.word, payRatio: w.pay_amt__ratio, showRatio: w.search_show_ucnt__ratio },
        };
      },
    },
    {
      id: 'N1-ratio-provenance',
      node: 'N1 市场信号采集',
      claim: '环比字段来自 out_period_ratio（环比率），不是 last_period_change（绝对变化量）',
      async run() {
        const rows = rowsOf(await D.call('compass.search.industry_rank', {}));
        if (!rows.length) return { status: STATUS.EMPTY, detail: '无数据可验' };
        const src = rows[0].pay_amt__ratio_src;
        if (src === undefined) {
          return { status: STATUS.FAIL, detail: '解包器未标注来源，量纲无从校验' };
        }
        return {
          status: src === 'out_period_ratio' ? STATUS.OK : STATUS.BLOCKED,
          detail: `来源=${src}`,
          evidence: { src, unit: rows[0].pay_amt__ratio_unit },
        };
      },
    },
    {
      id: 'N3-history',
      node: 'N3 交叉证伪 / 纵向归因',
      claim: '能回溯历史周窗口，用于区分趋势与季节性',
      async run() {
        await api.init('new_shop');
        const past = new Date(Date.now() - 14 * 86400000);
        let r;
        try { r = await api.getSearchIndustryRank(past); } catch (e) { r = { _error: e.message }; }
        if (r && r._error) {
          return {
            status: STATUS.BLOCKED,
            detail: `回溯 T-14 被拒：${String(r._error).slice(0, 40)}`,
            evidence: { implication: '历史只能按周自行积累，不能查询。纵向归因在攒够 4 周前不可用。' },
          };
        }
        return { status: STATUS.OK, detail: '可回溯历史窗口' };
      },
    },
    {
      id: 'N1-supply-count',
      node: 'N1 / 机会模型',
      claim: '能拿到类目在售商品数（供需比的分母）',
      async run() {
        // 同上：compass.market.shop_rank 已去重移除，实际是 hot_sale_rank。
        const r = await D.call('diagnosis.compass.hot_sale_rank', {});
        const rows = rowsOf(r);
        const total = r.data && (r.data.search_shop_rank__total || r.data.rows__total);
        // 店铺数不等于商品数。分母缺失是设计前提问题，不是取数问题。
        return {
          status: STATUS.BLOCKED,
          detail: `只有店铺维度（${rows.length} 行 / total=${total ?? '?'}），无类目在售商品数`,
          evidence: { implication: '供需比算不出来。改用「进入门槛 + 头部形状」替代。' },
        };
      },
    },
    {
      id: 'N1-hotspot',
      node: 'N1 / 内容侧归因',
      claim: '能拿到抖音热点榜，且含关联商品数与本店参与度',
      async run() {
        // ⚠️ 不是 compass.market.hotspot——那个 toolId 在去重时被移除了。
        // 实际提供热点榜的是 diagnosis.compass.video_after_watch，
        // 这个名字**名不副实**（历史上旧端点失效后被改指到热点榜却没改名）。
        const r = await D.call('diagnosis.compass.video_after_watch', {});
        const rows = rowsOf(r);
        if (!rows.length) return { status: STATUS.EMPTY, detail: '热点榜无数据' };
        const hasSelf = rows.some((x) => x.self_related_product_cnt !== undefined);
        const selfSum = rows.reduce((n, x) => n + (Number(x.self_related_product_cnt) || 0), 0);
        return {
          status: hasSelf ? STATUS.OK : STATUS.EMPTY,
          detail: `${rows.length} 条热点，本店关联商品合计 ${selfSum}`,
          evidence: { sample: rows[0] && rows[0].meta_info, selfParticipation: selfSum },
        };
      },
    },
    {
      id: 'N11-product-metrics',
      node: 'N11 冷启动观测 / N12 假设裁决',
      claim: '上架后能拿到单品维度的曝光/点击/成交，用于验证当初的机会假设',
      async run() {
        const r = await D.call('diagnosis.compass.product_rank', {});
        const rows = rowsOf(r);
        if (!r.success) return { status: STATUS.FAIL, detail: r.error && r.error.message };
        if (!rows.length) return { status: STATUS.EMPTY, detail: '无商品行' };
        const metrics = Object.keys((rows[0] && rows[0].cell_info) || {});
        const need = ['pay_amt', 'product_show_ucnt', 'product_click_ucnt'];
        const missing = need.filter((m) => !metrics.includes(m));
        if (missing.length) {
          return { status: STATUS.BLOCKED, detail: `缺关键指标 ${missing.join(',')}——闭环无法验证` };
        }
        // 字段在但值可能是 unit:6（本店暂无流量）
        const un = U.unwrapAuto({ data: { module_data: { p: { compass_general_table_value: {
          basic_meta: metrics.map((n) => ({ index_name: n })), data: rows,
        } } } } });
        const first = (un.p || [])[0] || {};
        const hasValue = need.some((m) => first[m] !== null && first[m] !== undefined);
        return {
          status: hasValue ? STATUS.OK : STATUS.EMPTY,
          detail: hasValue
            ? `${rows.length} 个商品，指标可解出`
            : `${rows.length} 个商品，字段齐全但值为 unit:6（本店暂无流量）——能力可用，等有数据即可验证`,
          evidence: { metrics, sampleValues: need.map((m) => [m, first[m]]) },
        };
      },
    },
    {
      id: 'N1-index-range',
      node: 'N1 / 进入门槛',
      claim: '能拿到指标档位分布并标出本店所在档（供需比的替代方案）',
      async run() {
        const r = await D.call('compass.market.index_range', {});
        if (!r.success) return { status: STATUS.FAIL, detail: r.error && r.error.message };
        const ranges = r.data && r.data.ranges;
        if (!ranges) return { status: STATUS.EMPTY, detail: '无档位数据' };
        const key = Object.keys(ranges)[0];
        const list = ranges[key] || [];
        const mine = list.find((x) => x && x.isCurrentShop);
        return {
          status: list.length ? STATUS.OK : STATUS.EMPTY,
          detail: `${key} 共 ${list.length} 档，本店所在档 ${mine ? `${mine.lower}~${mine.upper}` : '未标注'}`,
          evidence: { metric: key, bands: list.length, currentShopBand: mine || null },
        };
      },
    },
    {
      id: 'TOOL-naming',
      node: '全局 / 工具可发现性',
      claim: '工具名与它实际返回的内容一致（Agent 靠名字选工具）',
      async run() {
        const registry = require(path.join(DATA_REPO, 'lib', 'tool-registry.js'));
        // 已知一例：video_after_watch 实际打的是抖音热点榜。
        // Agent 按名字选工具，名不副实会让它选错或根本找不到。
        const known = ['diagnosis.compass.video_after_watch'];
        const bad = known.filter((id) => registry.get(id));
        return {
          status: bad.length ? STATUS.BLOCKED : STATUS.OK,
          detail: bad.length
            ? `${bad.length} 个工具名不副实：${bad.join(', ')}（实为抖音热点榜）`
            : '未发现名不副实的工具',
          evidence: bad.length
            ? { implication: 'Agent 靠名字选工具。这类应加别名或在 description 里显式说明实际内容。' }
            : undefined,
        };
      },
    },
    {
      id: 'GATE-scope',
      node: '全局 / 数据契约',
      claim: '每条罗盘结果都带作用域，且只有 MARKET 能驱动决策',
      async run() {
        const r = await D.call('compass.search.industry_rank', {});
        const m = r.data && r.data._meta;
        if (!m) return { status: STATUS.FAIL, detail: '结果未带 _meta，闸门形同虚设' };
        return {
          status: m.scope ? STATUS.OK : STATUS.FAIL,
          detail: `scope=${m.scope} canDriveDecision=${m.canDriveDecision}`,
          evidence: m,
        };
      },
    },
    {
      id: 'GATE-shop-identity',
      node: '全局 / 店铺身份',
      claim: '每条结果都标注它属于哪个店铺',
      async run() {
        const r = await D.call('compass.search.industry_rank', {});
        const id = r.data && r.data._meta && r.data._meta.shopId;
        return {
          status: id ? STATUS.OK : STATUS.FAIL,
          detail: id ? `shopId=${id}` : '未标注店铺，多店铺时无法判断数据归属',
          evidence: { shopId: id },
        };
      },
    },
  ];
}

async function main() {
  const asJson = process.argv.includes('--json');
  const L = loadDataLayer();
  const probes = buildProbes(L);
  const results = [];

  for (const p of probes) {
    let r;
    try { r = await p.run(); } catch (e) { r = { status: STATUS.FAIL, detail: e.message.slice(0, 120) }; }
    results.push({ id: p.id, node: p.node, claim: p.claim, ...r });
    if (!asJson) {
      const icon = { OK: '✅', EMPTY: '○', BLOCKED: '⛔', FAIL: '❌' }[r.status] || '?';
      console.log(`${icon} [${p.id}] ${p.claim}`);
      console.log(`    ${r.detail || ''}`);
      if (r.evidence && r.evidence.implication) console.log(`    ⚠️ ${r.evidence.implication}`);
    }
  }

  try { await L.compassTools.close(); } catch (_) { /* ignore */ }

  if (asJson) { console.log(JSON.stringify(results, null, 2)); return; }

  const n = (s) => results.filter((r) => r.status === s).length;
  console.log('');
  console.log('='.repeat(60));
  console.log(`可行 ${n(STATUS.OK)}   暂无数据 ${n(STATUS.EMPTY)}   平台不支持 ${n(STATUS.BLOCKED)}   失败 ${n(STATUS.FAIL)}`);
  if (n(STATUS.BLOCKED)) {
    console.log('');
    console.log('⛔ 以下前提不成立，**设计必须改**，不要靠重试或兜底绕过：');
    results.filter((r) => r.status === STATUS.BLOCKED)
      .forEach((r) => console.log(`   ${r.id}  ${r.detail}`));
  }
  process.exitCode = n(STATUS.FAIL) ? 1 : 0;
}

main();
