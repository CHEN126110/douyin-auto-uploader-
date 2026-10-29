// 验证用页面脚本：DOM + 计算样式快照、等待与点击小工具。
// 通过 http://127.0.0.1:<代理端口>/__ctl/harness.js 注入（默认 5003），快照回传给代理保存成文件。
(() => {
  // 代理地址取自本脚本自己的来源，不写死端口。
  const PROXY_ORIGIN = new URL(document.currentScript.src).origin;
  const CTL = `${PROXY_ORIGIN}/__ctl`;

  // 内置浏览器窗格在后台时 requestAnimationFrame 不触发（实测 2s 内无回调），
  // Vue / Element Plus 的过渡会卡在中间状态。这里用定时器代替 rAF，并关闭 CSS 过渡与动画，
  // 让计算样式直接取终态。仅用于验证，拆分前后的运行条件完全一致。
  if (!window.__rafShim) {
    window.__rafShim = true;
    window.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 16);
    window.cancelAnimationFrame = (id) => clearTimeout(id);
    const st = document.createElement("style");
    st.id = "__verify_no_motion";
    st.textContent = "*,*::before,*::after{transition:none!important;animation:none!important;scroll-behavior:auto!important}";
    document.head.appendChild(st);
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function waitFor(fn, { timeout = 10000, interval = 50, label = "条件" } = {}) {
    const start = Date.now();
    for (;;) {
      let v;
      try { v = await fn(); } catch (e) { v = null; }
      if (v) return v;
      if (Date.now() - start > timeout) throw new Error(`等待超时：${label}`);
      await sleep(interval);
    }
  }

  const q = (sel, root = document) => root.querySelector(sel);
  const qa = (sel, root = document) => [...root.querySelectorAll(sel)];
  const text = (el) => (el.textContent || "").replace(/\s+/g, " ").trim();
  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none";
  };
  const byText = (sel, t, root = document) => qa(sel, root).find((e) => visible(e) && text(e).includes(t));

  async function click(el, label = "") {
    if (!el) throw new Error(`找不到可点击元素 ${label}`);
    el.click();
    await sleep(60);
  }

  function setValue(input, value) {
    const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  // ---------- DOM 快照 ----------
  const STYLE_PROPS = [
    "display", "position", "boxSizing", "width", "height", "minWidth", "maxWidth", "minHeight", "maxHeight",
    "marginTop", "marginRight", "marginBottom", "marginLeft",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "borderTopWidth", "borderTopStyle", "borderTopColor", "borderRightWidth", "borderRightStyle", "borderRightColor",
    "borderBottomWidth", "borderBottomStyle", "borderBottomColor", "borderLeftWidth", "borderLeftStyle", "borderLeftColor",
    "borderTopLeftRadius", "borderTopRightRadius", "borderBottomLeftRadius", "borderBottomRightRadius",
    "color", "backgroundColor", "backgroundImage", "boxShadow", "opacity",
    "fontSize", "fontWeight", "fontStyle", "fontFamily", "lineHeight", "letterSpacing", "textAlign", "textTransform",
    "textOverflow", "whiteSpace", "wordBreak", "overflowX", "overflowY",
    "flexDirection", "flexWrap", "flexGrow", "flexShrink", "flexBasis", "alignItems", "alignSelf", "justifyContent",
    "rowGap", "columnGap", "gridTemplateColumns", "gridColumnStart", "gridColumnEnd",
    "transform", "cursor", "zIndex", "top", "right", "bottom", "left", "visibility", "pointerEvents",
    "outlineStyle", "outlineWidth", "borderCollapse", "verticalAlign", "listStyleType", "textDecorationLine",
  ];
  const norm = (s) =>
    String(s)
      .replace(/el-id-\d+-\d+/g, "el-id-*")
      .replace(/([?&]t=)\d+/g, "$1*")
      .replace(/\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?/g, "TS")
      .replace(/-\d{4,}(?=\W|$)/g, "-N");
  const ATTRS_SKIP = new Set(["style"]);

  function describe(el, depth) {
    const parts = [`${"  ".repeat(depth)}<${el.tagName.toLowerCase()}`];
    const attrs = [...el.attributes]
      .filter((a) => !a.name.startsWith("data-v-") && !ATTRS_SKIP.has(a.name))
      .map((a) => `${a.name}=${JSON.stringify(norm(a.value))}`)
      .sort();
    if (attrs.length) parts.push(attrs.join(" "));
    // 内联 style 另记，便于看出差异来源
    const inline = el.getAttribute("style");
    if (inline) parts.push(`style=${JSON.stringify(norm(inline))}`);
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) parts.push(`value=${JSON.stringify(el.value)}`);
    if (el instanceof HTMLInputElement && (el.type === "checkbox" || el.type === "radio")) parts.push(`checked=${el.checked}`);
    // <pre> 里的空白与换行有意义（要复制的命令 / JSON 配置），按原样记录
    if (el.tagName === "PRE") parts.push(`pre=${JSON.stringify(norm(el.textContent))}`);
    const r = el.getBoundingClientRect();
    parts.push(`rect=${r.x.toFixed(1)},${r.y.toFixed(1)},${r.width.toFixed(1)},${r.height.toFixed(1)}`);
    const cs = getComputedStyle(el);
    parts.push("css=" + STYLE_PROPS.map((p) => cs[p]).join("|"));
    return parts.join(" ");
  }

  function walk(node, depth, out) {
    if (node.nodeType === Node.TEXT_NODE) {
      const t = node.textContent.replace(/\s+/g, " ").trim();
      if (t) out.push(`${"  ".repeat(depth)}"${norm(t)}"`);
      return;
    }
    if (node.nodeType === Node.COMMENT_NODE) return;
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tag = node.tagName.toLowerCase();
    if (tag === "style" || tag === "script") return;
    out.push(describe(node, depth));
    // display:none 的子树（例如未激活的 tab 面板）不展开，只记一行
    if (getComputedStyle(node).display === "none") return;
    for (const child of node.childNodes) walk(child, depth + 1, out);
  }

  async function save(name, body) {
    const resp = await fetch(`${CTL}/capture?name=${encodeURIComponent(name)}`, {
      method: "POST", headers: { "Content-Type": "text/plain" }, body,
    });
    return resp.json();
  }

  const envLine = () => `#env dpr=${devicePixelRatio} viewport=${innerWidth}x${innerHeight}`;

  async function dump(name, selector) {
    const root = typeof selector === "string" ? q(selector) : selector;
    if (!root) throw new Error(`快照根节点不存在：${selector}`);
    const out = [envLine()];
    walk(root, 0, out);
    const info = await save(name, out.join("\n"));
    return `${name}: ${out.length} 行, ${info.bytes} 字节`;
  }

  async function dumpAll(name, selectors) {
    const out = [envLine()];
    for (const sel of selectors) {
      const root = q(sel);
      out.push(`#### ${sel}`);
      if (!root) { out.push("(不存在)"); continue; }
      walk(root, 0, out);
    }
    const info = await save(name, out.join("\n"));
    return `${name}: ${out.length} 行, ${info.bytes} 字节`;
  }

  async function ctl(path, body) {
    const resp = await fetch(`${CTL}/${path}`, { method: body ? "POST" : "GET", body: body ? JSON.stringify(body) : undefined });
    return resp.json();
  }

  // 全局 console 记录：用于对比拆分前后的控制台输出
  if (!window.__consoleLog) {
    window.__consoleLog = [];
    for (const level of ["log", "info", "warn", "error", "debug"]) {
      const orig = console[level].bind(console);
      console[level] = (...args) => {
        try {
          window.__consoleLog.push(`[${level}] ` + args.map((a) => (typeof a === "string" ? a : (a && a.message) || JSON.stringify(a))).join(" "));
        } catch (e) { /* ignore */ }
        orig(...args);
      };
    }
    window.addEventListener("error", (e) => window.__consoleLog.push(`[window.error] ${e.message}`));
    window.addEventListener("unhandledrejection", (e) => window.__consoleLog.push(`[unhandledrejection] ${e.reason && e.reason.message || e.reason}`));
  }

  // 让页面认为自己「不可见」：App.vue 的 30 秒商品同步、外部任务发现、账户栏轮询都会因此跳过，
  // 避免这些后台定时器在脚本运行期间插进来，造成与代码无关的请求 / 列表差异。返回恢复函数。
  const quiet = () => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    return () => { delete document.visibilityState; delete document.hidden; };
  };
  const toasts = () => qa(".el-message .el-message__content").map(text);

  // 安全闸：被测前端实际使用的后端地址必须就是验证代理。
  // 前端写死 127.0.0.1:5001，而 5001 是真实桌面应用的 Sidecar（里面是用户的真实数据）；验证用的开发服务器
  // 由 vite.ab.config.mts 把它改写成代理端口。万一改写没生效，场景里的保存 / 删除 / 清空就会打到真实数据上，
  // 所以每个场景开跑前先核对，对不上就直接中止，什么都不做。
  async function assertBackend() {
    const mod = await import(`${location.origin}/src/services/api.ts`);
    const backend = String(mod.BACKEND_URL);
    if (new URL(backend).origin !== PROXY_ORIGIN) {
      throw new Error(`被测前端的后端地址是 ${backend}，不是验证代理 ${PROXY_ORIGIN}：已中止，避免打到真实后端。` +
        "请确认这个前端开发服务器是用 vite.ab.config.mts 启动的。");
    }
    return backend;
  }

  window.__H = { quiet, toasts, sleep, waitFor, q, qa, text, visible, byText, click, setValue, dump, dumpAll, save, ctl, assertBackend };

  // 场景脚本只管 `window.__scn.xxx = async function ...`；这里让每个场景函数开跑前先过上面的安全闸。
  window.__scn = new Proxy({}, {
    set(target, key, value) {
      target[key] = typeof value === "function"
        ? async function (...args) { await assertBackend(); return value.apply(this, args); }
        : value;
      return true;
    },
  });
})();
