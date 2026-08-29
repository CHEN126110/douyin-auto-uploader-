/* ============================================================
   抖店经营 · 2.5D 驾驶舱 — 前端逻辑
   同源直连 business_api：所有数据来自 /health、/catalog 与各 /api/<域> 接口。
   设计：站台显示关键数字，点击展开域详情；浏览器/登录未就绪时优雅降级，不假装有数据。
   ============================================================ */
(function () {
  "use strict";

  // ---------- 通用请求 ----------
  async function api(path, body) {
    const opt = { method: body === undefined ? "GET" : "POST", headers: {} };
    if (body !== undefined) {
      opt.headers["Content-Type"] = "application/json";
      opt.body = JSON.stringify(body || {});
    }
    const resp = await fetch(path, opt);
    let json = null;
    try { json = await resp.json(); } catch (_) { json = null; }
    return { status: resp.status, body: json };
  }

  // 把后端错误码翻译成驾驶舱可读的连接状态
  const STATE = { OK: "ok", LOGIN: "login", BROWSER: "browser", ERROR: "error" };
  function classify(res) {
    if (res.body && res.body.ok) return { state: STATE.OK, data: res.body.data, msg: res.body.message };
    const code = (res.body && res.body.code) || "";
    if (code === "LOGIN_REQUIRED") return { state: STATE.LOGIN, hint: res.body.hint };
    if (code === "BROWSER_NOT_READY") return { state: STATE.BROWSER, hint: res.body.hint };
    if (code === "CAPTCHA_REQUIRED") return { state: STATE.BROWSER, hint: res.body.hint || "命中验证码，请在浏览器完成验证" };
    return { state: STATE.ERROR, code, hint: (res.body && (res.body.hint || res.body.message)) || "接口异常" };
  }

  // ---------- 业务域配置 ----------
  // 每个域：取数接口 + 站台关键指标提取 + 抽屉渲染
  const DOMAINS = [
    {
      key: "compass", name: "电商罗盘", tag: "经营核心", icon: "📊", accent: "#5b8cff",
      endpoint: "/api/compass/overview", payload: { limit: 50 },
      metric(d) {
        const v = (d.by_label && (d.by_label["成交金额"] || d.by_label["用户支付金额"])) || "-";
        return { num: v, unit: "", sub: "今日成交金额" };
      },
      render(d) {
        const note = `<div class="drawer-note">${esc(d.note || "")}</div>`;
        const rows = (d.metrics || []).map(m => {
          const cmp = m.benchmark
            ? `${esc(m.benchmark_type || "同行")} ${esc(m.benchmark)}`
            : "无同行对比";
          const nodata = (m.value === "-" || m.value === "");
          return rowItem({
            title: esc(m.label),
            badge: nodata ? "暂无数据" : esc(m.value),
            badgeCls: nodata ? "" : "ok",
            meta: [`昨日 ${esc(m.yesterday || "-")}`, cmp],
          });
        }).join("");
        return note + (rows || emptyState("暂无指标"));
      },
    },
    {
      key: "product", name: "商品", tag: "在售管理", icon: "📦", accent: "#27d3a2",
      endpoint: "/api/product/list", payload: { limit: 30 },
      metric(d) {
        const top = (d.items && d.items[0] && d.items[0].title) || "";
        return { num: d.count, unit: "在售", sub: top ? "热门：" + top.slice(0, 12) : "暂无商品" };
      },
      render(d) {
        const rows = (d.items || []).map(it => rowItem({
          title: esc(it.title || "(无标题)"),
          badge: esc(it.status || ""),
          badgeCls: it.status && it.status.indexOf("出售") >= 0 ? "ok" : "warn",
          meta: [`价 ${esc(it.price || "-")}`, `销 ${esc(it.sales || "-")}`, idText(it.product_id)],
        })).join("");
        return rows || emptyState("暂无商品");
      },
    },
    {
      key: "order", name: "订单", tag: "发货履约", icon: "🧾", accent: "#ff9f43",
      endpoint: "/api/order/list", payload: { limit: 30 },
      metric(d) {
        const pend = (d.items || []).filter(i => (i.status || "").indexOf("待发货") >= 0).length;
        return { num: d.count, unit: "笔", sub: pend ? `待发货 ${pend} 笔` : "无待发货" };
      },
      render(d) {
        const rows = (d.items || []).map(it => rowItem({
          title: esc((it.product || "(商品)").slice(0, 22)),
          badge: esc(it.status || ""),
          badgeCls: badgeForOrder(it.status),
          meta: [`实付 ${esc(it.paid || "-")}`, idText(it.order_id)],
        })).join("");
        return rows || emptyState("暂无订单");
      },
    },
    {
      key: "aftersale", name: "售后", tag: "退款处理", icon: "🛟", accent: "#ff6b81",
      endpoint: "/api/aftersale/list", payload: { limit: 30 },
      metric(d) {
        const todo = (d.items || []).filter(i => (i.aftersale_status || "").indexOf("待商家") >= 0).length;
        return { num: d.count, unit: "单", sub: todo ? `待处理 ${todo} 单` : "无待处理" };
      },
      render(d) {
        const rows = (d.items || []).map(it => rowItem({
          title: esc((it.product || "(商品)").slice(0, 22)),
          badge: esc(it.aftersale_status || ""),
          badgeCls: (it.aftersale_status || "").indexOf("待商家") >= 0 ? "warn" : "",
          meta: [`退款 ${esc(it.refund || "-")}`, esc(it.intervene || ""), idText(it.order_id)],
        })).join("");
        return rows || emptyState("暂无售后单");
      },
    },
    {
      key: "marketing", name: "营销活动", tag: "优惠投放", icon: "🎯", accent: "#a55eea",
      endpoint: "/api/marketing/activities", payload: { limit: 30 },
      metric(d) {
        const live = (d.items || []).filter(i => (i.status || "").indexOf("进行中") >= 0).length;
        return { num: live, unit: "进行中", sub: `共 ${d.count} 个活动` };
      },
      render(d) {
        const rows = (d.items || []).map(it => rowItem({
          title: esc(it.name || "(活动)"),
          badge: esc(it.status || ""),
          badgeCls: (it.status || "").indexOf("进行中") >= 0 ? "ok" : "",
          meta: [esc(it.activity_type || ""), esc(it.period || ""), it.effect ? esc(it.effect) : ""],
        })).join("");
        return rows || emptyState("暂无营销活动");
      },
    },
  ];

  // ---------- DOM 工具 ----------
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, c => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }
  function idText(id) { return id ? `<span class="row-id">#${esc(id)}</span>` : ""; }
  function badgeForOrder(s) {
    s = s || "";
    if (s.indexOf("待发货") >= 0) return "warn";
    if (s.indexOf("已完成") >= 0 || s.indexOf("已签收") >= 0) return "ok";
    if (s.indexOf("退") >= 0 || s.indexOf("关闭") >= 0) return "bad";
    return "";
  }
  function rowItem({ title, badge, badgeCls, meta }) {
    const metas = (meta || []).filter(Boolean).map(m => `<span>${m}</span>`).join("");
    return `<div class="row-item">
      <div class="row-line"><span class="row-title">${title}</span>
      ${badge ? `<span class="row-badge ${badgeCls || ""}">${badge}</span>` : ""}</div>
      <div class="row-meta">${metas}</div></div>`;
  }
  function emptyState(text) { return `<div class="state-msg"><span class="big">∅</span>${esc(text)}</div>`; }
  function stateMsg(c) {
    const map = {
      [STATE.LOGIN]: ["🔑", "未登录 / 登录态失效", "请在被接管的 Chrome 中登录抖店后点刷新"],
      [STATE.BROWSER]: ["🧭", "浏览器未就绪", "请确认调试 Chrome 已启动（9222）后点刷新"],
      [STATE.ERROR]: ["⚠️", "数据获取失败", ""],
    };
    const [icon, t, h] = map[c.state] || map[STATE.ERROR];
    return `<div class="state-msg err"><span class="big">${icon}</span>${esc(t)}
      <div style="margin-top:8px;font-size:12px">${esc(c.hint || h || "")}</div></div>`;
  }

  // ---------- 渲染站台 ----------
  const cache = {};        // key -> {state, data, c}
  const elStations = document.getElementById("stations");

  function stationCard(dom) {
    return `<article class="station loading" data-key="${dom.key}" style="--st:${dom.accent}">
      <div class="station-top">
        <div class="station-icon">${dom.icon}</div>
        <div><div class="station-name">${dom.name}</div><div class="station-tag">${dom.tag}</div></div>
      </div>
      <div class="station-metric"><span class="station-num" data-num>…</span><span class="station-unit" data-unit></span></div>
      <div class="station-sub" data-sub>加载中…</div>
      <div class="station-foot"><span data-foot>—</span><span class="enter">进入 ›</span></div>
    </article>`;
  }

  function paintStation(dom, c) {
    const el = elStations.querySelector(`[data-key="${dom.key}"]`);
    if (!el) return;
    el.classList.remove("loading", "err");
    const num = el.querySelector("[data-num]");
    const unit = el.querySelector("[data-unit]");
    const sub = el.querySelector("[data-sub]");
    const foot = el.querySelector("[data-foot]");
    if (c.state === STATE.OK) {
      const m = dom.metric(c.data || {});
      num.textContent = m.num;
      unit.textContent = m.unit || "";
      sub.textContent = m.sub || "";
      foot.textContent = "实时 · 点击查看明细";
    } else {
      el.classList.add("err");
      num.textContent = "—";
      unit.textContent = "";
      sub.textContent = c.state === STATE.LOGIN ? "未登录" :
                        c.state === STATE.BROWSER ? "浏览器未就绪" : "获取失败";
      foot.textContent = "点击查看原因";
    }
  }

  async function loadDomain(dom) {
    const res = await api(dom.endpoint, dom.payload || {});
    const c = classify(res);
    cache[dom.key] = c;
    paintStation(dom, c);
    return c;
  }

  // ---------- 罗盘 KPI 浮层 ----------
  const KPI_LABELS = ["成交金额", "用户支付金额", "成交订单数", "商品曝光人数", "商品点击人数", "退款金额（退款时间）"];
  function paintKpis(c) {
    const row = document.getElementById("kpiRow");
    if (c.state !== STATE.OK) { row.innerHTML = `<div class="kpi-empty">${esc((stateLabel(c)))}</div>`; return; }
    const metrics = (c.data && c.data.metrics) || [];
    const byLabel = {};
    metrics.forEach(m => { byLabel[m.label] = m; });
    const picks = KPI_LABELS.map(l => byLabel[l]).filter(Boolean);
    const list = picks.length ? picks : metrics.slice(0, 6);
    row.innerHTML = list.map(m => {
      const nodata = (m.value === "-" || m.value === "");
      const cmp = m.benchmark ? `${esc(m.benchmark_type || "同行")} <b>${esc(m.benchmark)}</b>` : "";
      return `<div class="kpi">
        <div class="kpi-label">${esc(m.label)}</div>
        <div class="kpi-value ${nodata ? "nodata" : ""}">${nodata ? "暂无" : esc(m.value)}</div>
        <div class="kpi-cmp">昨日 ${esc(m.yesterday || "-")} · ${cmp || "—"}</div>
      </div>`;
    }).join("") || `<div class="kpi-empty">暂无指标</div>`;
  }
  function stateLabel(c) {
    if (c.state === STATE.LOGIN) return "未登录，登录后显示罗盘指标";
    if (c.state === STATE.BROWSER) return "浏览器未就绪，启动后显示";
    return c.hint || "罗盘数据获取失败";
  }

  // ---------- 抽屉 ----------
  const drawer = document.getElementById("drawer");
  const scrim = document.getElementById("scrim");
  function openDrawer(dom) {
    document.getElementById("drawerIcon").textContent = dom.icon;
    document.getElementById("drawerName").textContent = dom.name;
    const body = document.getElementById("drawerBody");
    const countEl = document.getElementById("drawerCount");
    const foot = document.getElementById("drawerFoot");
    const c = cache[dom.key];
    if (!c) { body.innerHTML = emptyState("加载中…"); }
    else if (c.state === STATE.OK) {
      countEl.textContent = (c.data && (c.data.count != null ? c.data.count + " 条" :
                            (c.data.metrics ? c.data.metrics.length + " 项" : ""))) || "";
      body.innerHTML = dom.render(c.data || {});
      foot.textContent = "数据来自真实页面 DOM · 已隐去买家隐私";
    } else {
      countEl.textContent = "";
      body.innerHTML = stateMsg(c);
      foot.textContent = "解决后点顶部「刷新」重试";
    }
    drawer.classList.add("show");
    drawer.setAttribute("aria-hidden", "false");
    scrim.classList.add("show");
  }
  function closeDrawer() {
    drawer.classList.remove("show");
    drawer.setAttribute("aria-hidden", "true");
    scrim.classList.remove("show");
  }
  document.getElementById("drawerClose").addEventListener("click", closeDrawer);
  scrim.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });

  // ---------- 顶部状态灯 ----------
  function updateChips() {
    const states = Object.values(cache).map(c => c.state);
    const anyOk = states.includes(STATE.OK);
    const anyLogin = states.includes(STATE.LOGIN);
    const anyBrowser = states.includes(STATE.BROWSER);
    const chipB = document.getElementById("chipBrowser");
    const chipL = document.getElementById("chipLogin");
    // 浏览器：只要有任一域成功或返回登录态，说明浏览器已连上
    setChip(chipB, (anyOk || anyLogin) ? "on" : (anyBrowser ? "off" : "warn"));
    // 登录：有域成功即视为已登录；全部登录态失效则 off
    setChip(chipL, anyOk ? "on" : (anyLogin ? "off" : "warn"));
    const sub = document.getElementById("hudSubtitle");
    if (anyOk) sub.textContent = "经营数据已连接 · 实时驾驶舱";
    else if (anyLogin) sub.textContent = "浏览器已连接，但未登录抖店";
    else if (anyBrowser) sub.textContent = "等待调试浏览器就绪…";
    else sub.textContent = "无法连接经营数据，请检查后端与浏览器";
  }
  function setChip(el, st) { el.classList.remove("on", "off", "warn"); el.classList.add(st); }

  // ---------- 视差 2.5D ----------
  const world = document.getElementById("world");
  const scene = document.getElementById("scene");
  let tx = 0, ty = 0, cx = 0, cy = 0;
  scene.addEventListener("mousemove", e => {
    const r = scene.getBoundingClientRect();
    tx = ((e.clientX - r.left) / r.width - 0.5);
    ty = ((e.clientY - r.top) / r.height - 0.5);
  });
  scene.addEventListener("mouseleave", () => { tx = 0; ty = 0; });
  (function loop() {
    cx += (tx - cx) * 0.06;
    cy += (ty - cy) * 0.06;
    world.style.transform = `rotateX(${(-cy * 6).toFixed(2)}deg) rotateY(${(cx * 8).toFixed(2)}deg)`;
    requestAnimationFrame(loop);
  })();

  // ---------- 背景景深粒子 ----------
  (function bg() {
    const cv = document.getElementById("bgCanvas");
    const ctx = cv.getContext("2d");
    let W, H, pts;
    function resize() {
      W = cv.width = window.innerWidth;
      H = cv.height = window.innerHeight;
      pts = Array.from({ length: 70 }, () => ({
        x: Math.random() * W, y: Math.random() * H,
        z: Math.random() * 1 + 0.3, r: Math.random() * 1.6 + 0.4,
      }));
    }
    function tick() {
      ctx.clearRect(0, 0, W, H);
      for (const p of pts) {
        p.y += p.z * 0.25;
        if (p.y > H) { p.y = -5; p.x = Math.random() * W; }
        ctx.beginPath();
        ctx.arc(p.x + cx * 30 * p.z, p.y + cy * 18 * p.z, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(140,170,255,${0.10 + p.z * 0.12})`;
        ctx.fill();
      }
      requestAnimationFrame(tick);
    }
    window.addEventListener("resize", resize);
    resize(); tick();
  })();

  // ---------- 时钟 ----------
  setInterval(() => {
    document.getElementById("hudClock").textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  }, 1000);

  // ---------- 启动 / 刷新 ----------
  const btn = document.getElementById("btnRefresh");
  async function refreshAll() {
    btn.classList.add("spin");
    elStations.querySelectorAll(".station").forEach(s => s.classList.add("loading"));
    const results = await Promise.all(DOMAINS.map(d => loadDomain(d).catch(() => ({ state: STATE.ERROR }))));
    // 罗盘单独喂给 KPI 浮层
    const compassC = cache["compass"];
    if (compassC) paintKpis(compassC);
    updateChips();
    btn.classList.remove("spin");
  }

  function mount() {
    elStations.innerHTML = DOMAINS.map((d, i) => stationCard(d)).join("");
    elStations.querySelectorAll(".station").forEach((el, i) => {
      el.style.animationDelay = (i * 70) + "ms";
      el.addEventListener("click", () => openDrawer(DOMAINS[i]));
    });
    refreshAll();
  }
  btn.addEventListener("click", refreshAll);
  document.addEventListener("DOMContentLoaded", mount);
  if (document.readyState !== "loading") mount();
})();
