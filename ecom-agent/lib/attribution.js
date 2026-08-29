/**
 * 归因：这个数据为什么会动？
 *
 * ── 为什么必须做归因 ────────────────────────────────────────
 * 用户的原话：「获取数据的背后是什么推动的，其中的原因希望我们可以分析出来，
 * **避免误导了方向**。」
 *
 * 这不是锦上添花。举个本项目实测到的例子：
 *
 *   篮球袜   成交环比 +26.7%   曝光环比  +6.1%
 *
 * 单看这一行，像是「需求在深化」的好机会。但把类目基准算出来之后：
 *
 *   类目成交基准（中位数） +25.2%
 *
 * 篮球袜的 +26.7% 只比大盘高 1.5 个百分点——**它根本不突出**，
 * 整个袜子类目都在涨。真正让它不一样的是曝光只涨 6.1%（比基准低 10.3pp），
 * 也就是「用更少的流量做到了同样的增长」，是效率好，不是需求爆发。
 *
 * 同一个数字，归因前后的结论完全不同。这就是「误导方向」的具体样子。
 *
 * ── 两层归因 ────────────────────────────────────────────────
 *
 * **第一层 横向归因（现在能做）**
 *   把「这个词自己的变化」从「整个类目的变化」里剥出来。
 *   再用抖音热点榜找出类目级变化的内容侧成因。
 *
 * **第二层 纵向归因（现在做不了，必须先攒历史）**
 *   区分：持续趋势 / 季节性 / 一次性事件。
 *   实测：罗盘的行业搜索词榜**只服务当前周**，回溯任何更早的窗口都返回
 *   「参数校验失败」。快照库目前也只有 1 个周窗口。
 *   所以历史**只能靠自己按周积累，不能查**。
 *
 * 在攒够历史之前，本模块对「这是趋势还是季节性」一律回答**不知道**，
 * 而不是猜一个。猜错的代价是按季节性机会去备货，结果季节过了。
 */
'use strict';

/** 超额幅度小于此值，视为跟随大盘，没有个体信号。 */
const EXCESS_THRESHOLD = 0.02;

const CAUSE = Object.freeze({
  CATEGORY_WIDE: 'category_wide',       // 整个类目在动，不是这个词的事
  WORD_SPECIFIC: 'word_specific',       // 扣掉大盘后仍显著，是这个词自己的信号
  EFFICIENCY: 'efficiency_gain',        // 成交跟上大盘但花的流量更少
  TRAFFIC_FED: 'traffic_fed',           // 拿到了额外流量但成交没跟上
  UNKNOWN: 'unknown',
});

/**
 * 计算类目基准。用中位数而不是均值——榜单里常有一个量级远超其他的词
 * （实测：日抛袜子 +66% vs 其余 18~25%），均值会被它拉偏。
 */
function categoryBaseline(rows) {
  const pays = rows.map((r) => num(r.pay_amt__ratio)).filter((x) => x !== null);
  const shows = rows.map((r) => num(r.search_show_ucnt__ratio)).filter((x) => x !== null);
  if (pays.length < 3 || shows.length < 3) {
    // 样本太少，中位数没有代表性。宁可不给基准，也不要给一个凭 2 个点算出来的。
    return { pay: null, show: null, sampleSize: Math.min(pays.length, shows.length), reliable: false };
  }
  return { pay: median(pays), show: median(shows), sampleSize: pays.length, reliable: true };
}

/**
 * 横向归因：把个体信号从大盘里剥出来。
 *
 * @param {object} row      单个搜索词
 * @param {object} baseline categoryBaseline 的结果
 */
function attributeHorizontal(row, baseline) {
  const pay = num(row.pay_amt__ratio);
  const show = num(row.search_show_ucnt__ratio);

  if (pay === null || show === null) {
    return { cause: CAUSE.UNKNOWN, note: '缺环比数据，无法归因', excessPay: null, excessShow: null };
  }
  if (!baseline.reliable) {
    return {
      cause: CAUSE.UNKNOWN,
      note: `榜单只有 ${baseline.sampleSize} 个有效样本，算不出可靠的类目基准——` +
        '此时任何「超额」判断都是拿噪音当信号',
      excessPay: null, excessShow: null,
    };
  }

  const ep = pay - baseline.pay;
  const es = show - baseline.show;
  const out = { excessPay: ep, excessShow: es };

  if (Math.abs(ep) <= EXCESS_THRESHOLD && Math.abs(es) <= EXCESS_THRESHOLD) {
    return { ...out, cause: CAUSE.CATEGORY_WIDE,
      note: '成交与曝光都贴着类目基准——变化来自整个类目，不是这个词自己的机会' };
  }
  if (ep > EXCESS_THRESHOLD && es > EXCESS_THRESHOLD) {
    return { ...out, cause: CAUSE.WORD_SPECIFIC,
      note: '成交与曝光都显著超出类目基准——这个词自己在发生事情，需要查明成因' };
  }
  if (Math.abs(ep) <= EXCESS_THRESHOLD && es < -EXCESS_THRESHOLD) {
    return { ...out, cause: CAUSE.EFFICIENCY,
      note: '成交跟上大盘但曝光增长远低于大盘——转化效率优于同类，投入产出比更好' };
  }
  if (ep < -EXCESS_THRESHOLD && es > EXCESS_THRESHOLD) {
    return { ...out, cause: CAUSE.TRAFFIC_FED,
      note: '拿到了高于大盘的流量但成交没跟上——警惕：流量可能来自平台扶持或蹭热点' };
  }
  return { ...out, cause: CAUSE.UNKNOWN, note: '超额方向混合，单期数据不足以归因' };
}

/**
 * 内容侧归因：用抖音热点榜解释类目级变化。
 *
 * 实测（2026-08-29，袜子类目）：热点榜 331 条中取 50 条，
 * 11 条是秋季换季主题（秋日citygirl穿搭 / 秋季外套大测评 / 早秋封神穿搭…），
 * 指向类目普涨的成因是**换季**。
 *
 * 同时 50 条的 self_related_product_cnt **全为 0**——本店一个热点都没参与。
 *
 * @param {Array}  hotspots 热点榜行（compass.market.hotspot 解包后）
 * @param {RegExp} themeRe  与本类目相关的主题正则
 */
function attributeContent(hotspots, themeRe) {
  const rows = Array.isArray(hotspots) ? hotspots : [];
  if (!rows.length) {
    return { matched: [], coverage: 0, selfParticipation: null,
      note: '热点榜无数据，内容侧归因不可用' };
  }
  const matched = rows.filter((r) => themeRe.test(String(r.meta_info || '')));
  const selfCnt = rows.reduce((n, r) => n + (num(r.self_related_product_cnt) || 0), 0);
  return {
    matched: matched.map((r) => ({
      topic: r.meta_info, level: r.hot_level,
      relatedProducts: num(r.related_product_cnt),
      selfProducts: num(r.self_related_product_cnt),
    })),
    coverage: matched.length / rows.length,
    selfParticipation: selfCnt,
    note: selfCnt === 0
      ? `本店在这 ${rows.length} 个热点中关联商品数为 0——完全没有参与内容侧流量`
      : `本店在 ${rows.length} 个热点中共关联 ${selfCnt} 个商品`,
  };
}

/**
 * 纵向归因：趋势 / 季节性 / 一次性事件。
 *
 * **当前一律返回 unavailable。** 这不是没实现，是数据条件不具备：
 * 罗盘的行业搜索词榜只服务当前周，回溯更早窗口返回「参数校验失败」；
 * 本地快照库目前只积累了 1 个周窗口。
 *
 * 给一个猜测的答案比不给更危险——按「季节性」判断会错过长期机会，
 * 按「趋势」判断会在季节过后砸手里。
 */
function attributeTemporal(wordHistory) {
  const n = Array.isArray(wordHistory) ? wordHistory.length : 0;
  if (n < 4) {
    return {
      available: false, periods: n,
      note: `纵向归因需要至少 4 个周窗口，当前只有 ${n} 个。` +
        '罗盘不支持回溯查询，历史只能按周自行积累——' +
        '在攒够之前，「这是趋势还是季节性」的答案是**不知道**，不要猜。',
    };
  }
  return { available: true, periods: n, note: '数据充足，可做趋势判定（待实现）' };
}

function median(a) {
  const s = [...a].sort((x, y) => x - y);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function num(v) { return (typeof v === 'number' && Number.isFinite(v)) ? v : null; }

module.exports = {
  CAUSE, EXCESS_THRESHOLD,
  categoryBaseline, attributeHorizontal, attributeContent, attributeTemporal,
};
