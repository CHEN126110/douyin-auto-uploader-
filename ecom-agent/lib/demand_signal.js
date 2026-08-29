/**
 * 需求真实性判据。
 *
 * ── 要解决的问题 ────────────────────────────────────────────
 * 用户的原话：「你怎么知道他可以卖？因为你知道其中的真实需求是存在的。」
 *
 * 难点在于「搜索量涨了」这一个表象下面，藏着两种相反的情况：
 *
 *   A. 真实需求深化——进来的人更愿意买了
 *   B. 蹭到热点或吃到平台流量扶持——人变多了但没人买
 *
 * 光看增长率，A 和 B 长得一模一样，而对「要不要进场」的结论完全相反。
 *
 * ── 判据 ────────────────────────────────────────────────────
 * 比较**成交增速**与**曝光增速**的方向：
 *
 *   成交增速 > 曝光增速  →  转化在改善，需求在深化
 *   成交增速 < 曝光增速  →  流量涨了但没转化，需求没跟上
 *
 * 实测（袜子类目，2026-08-29 周口径）：
 *
 *   篮球袜    成交 +26.7%  曝光  +6.1%  →  背离 +20.6  需求深化
 *   日抛袜子  成交 +66.4%  曝光 +78.6%  →  背离 -12.1  流量虚高
 *
 * 日抛袜子的**表面增速最高**，却是这批里最不该进的。
 *
 * ── 这个判据不能做什么 ──────────────────────────────────────
 * - 只有单期环比，**无法区分季节性**。篮球袜在开学季涨，未必是长期趋势。
 *   要判季节性得跨年同比，而罗盘当前拿不到。
 * - 行业数据是**区间**不是精确值，环比本身也来自平台计算，我们无法复核它的分母。
 * - 曝光与成交的口径可能不完全对齐（曝光是人数，成交是金额）。
 *
 * 所以本模块输出的是**信号**，不是结论。它负责把「值得细看的」和
 * 「看起来热闹但可疑的」分开，最终判断仍要人来做。
 */
'use strict';

/** 背离超过这个幅度才算方向明确，以内视为同步增长。 */
const DIVERGENCE_THRESHOLD = 0.03;

/** 增速低于此值视为没有增长，不参与背离判定。 */
const FLAT_THRESHOLD = 0.02;

const VERDICT = Object.freeze({
  DEEPENING: 'demand_deepening',     // 成交增速明显快于曝光——需求在深化
  INFLATED: 'traffic_inflated',      // 曝光增速明显快于成交——流量虚高
  SYNCHRONIZED: 'synchronized',      // 两者同步——正常增长
  FLAT: 'flat',                      // 都没怎么动
  DECLINING: 'declining',            // 都在跌
  UNKNOWN: 'unknown',                // 数据不足，拒绝判定
});

const VERDICT_NOTE = Object.freeze({
  [VERDICT.DEEPENING]: '成交增速快于曝光增速——进来的人更愿意买了，需求在深化',
  [VERDICT.INFLATED]: '曝光增速快于成交增速——流量涨了但没转化，可能是蹭热点或平台流量扶持',
  [VERDICT.SYNCHRONIZED]: '成交与曝光同步增长——正常放量，无额外信号',
  [VERDICT.FLAT]: '成交与曝光都无明显变化',
  [VERDICT.DECLINING]: '成交与曝光都在下降',
  [VERDICT.UNKNOWN]: '缺少环比数据，无法判定——不要当作「没有信号」',
});

/**
 * 判定一个搜索词的需求真实性。
 *
 * @param {object} row 行业搜索词榜的一行（compass.search.industry_rank 解包后）
 * @param {number} row.pay_amt__ratio          成交额环比
 * @param {number} row.search_show_ucnt__ratio 搜索曝光人数环比
 * @returns {{verdict:string, note:string, divergence:number|null, payRatio:number|null, showRatio:number|null}}
 */
function assessDemand(row) {
  // 先验来源：只有 out_period_ratio 是「环比率」，last_period_change 是
  // 「环比绝对变化量」。两者曾被解包器写进同一个 __ratio 键，
  // 拿绝对变化量当增长率算，会得到一个量纲完全错误却看不出错的结论。
  const bad = ['pay_amt', 'search_show_ucnt'].filter((f) => {
    const src = row && row[f + '__ratio_src'];
    return src !== undefined && src !== 'out_period_ratio';
  });
  if (bad.length) {
    return {
      verdict: VERDICT.UNKNOWN,
      note: `${bad.join('、')} 的环比来自 last_period_change（绝对变化量）而非环比率，` +
        '当增长率用会产生量纲错误——拒绝判定',
      divergence: null, payRatio: null, showRatio: null,
    };
  }

  const pay = numOrNull(row && row.pay_amt__ratio);
  const show = numOrNull(row && row.search_show_ucnt__ratio);

  // 缺任一环比就拒绝判定。给一个「同步增长」的默认值等于制造假信号。
  if (pay === null || show === null) {
    return {
      verdict: VERDICT.UNKNOWN, note: VERDICT_NOTE[VERDICT.UNKNOWN],
      divergence: null, payRatio: pay, showRatio: show,
    };
  }

  const divergence = pay - show;

  if (pay < -FLAT_THRESHOLD && show < -FLAT_THRESHOLD) {
    return mk(VERDICT.DECLINING, divergence, pay, show);
  }
  if (Math.abs(pay) <= FLAT_THRESHOLD && Math.abs(show) <= FLAT_THRESHOLD) {
    return mk(VERDICT.FLAT, divergence, pay, show);
  }
  if (divergence > DIVERGENCE_THRESHOLD) return mk(VERDICT.DEEPENING, divergence, pay, show);
  if (divergence < -DIVERGENCE_THRESHOLD) return mk(VERDICT.INFLATED, divergence, pay, show);
  return mk(VERDICT.SYNCHRONIZED, divergence, pay, show);
}

function mk(verdict, divergence, payRatio, showRatio) {
  return { verdict, note: VERDICT_NOTE[verdict], divergence, payRatio, showRatio };
}

function numOrNull(v) {
  return (typeof v === 'number' && Number.isFinite(v)) ? v : null;
}

module.exports = {
  VERDICT, VERDICT_NOTE, DIVERGENCE_THRESHOLD, FLAT_THRESHOLD,
  assessDemand,
};
