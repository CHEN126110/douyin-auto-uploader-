/**
 * 淘宝发布工作台的页面内勘察表达式（共享模块）。
 *
 * 两个脚本都用它，避免同一段 3.6KB 的 JS 在两处维护：
 *   - probe-publish-workbench.mjs  —— 一次性结构勘察（DETAIL）
 *   - watch-publish-flow.mjs       —— 流程观察，每次页面变化落一份（DETAIL + FINGERPRINT）
 *
 * ## 只读保证
 *
 * 这两个表达式**只读页面**：
 *   - 不调用任何 `click()` / `focus()` / `dispatchEvent()` / `scrollTo()`
 *   - 不读取任何输入框的 `value`（页面可能已被卖家填过资料）
 *   - 不写入 `document`、不改 DOM、不发请求
 *
 * 它们能做的只有：`querySelectorAll` + 读属性 + 读文本。
 *
 * ## 为什么指纹要单独一份
 *
 * 流程观察器每 1.5 秒轮询一次，需要一个**便宜**的「页面变了没有」判据。
 * 直接跑 DETAIL 太贵（要遍历几万个节点）。FINGERPRINT 只取几个轻量计数与
 * 少量标签文本，成本与页面大小基本无关。
 */

/** 详情快照：控件的识别性属性 + 业务关键词分区。**刻意不取 value。** */
export const DETAIL_EXPRESSION = String.raw`(() => {
  const trim = (value, limit = 120) => String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, limit);
  const visible = (el) => {
    try {
      if (!el || !el.getBoundingClientRect) return false;
      const rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
      const style = window.getComputedStyle(el);
      return style.visibility !== "hidden" && style.display !== "none";
    } catch (e) { return false; }
  };

  /** 只取识别用途的属性，**刻意不取 value**。 */
  const describeControl = (el) => ({
    tag: el.tagName ? el.tagName.toLowerCase() : "",
    type: trim(el.getAttribute("type")),
    id: trim(el.id),
    name: trim(el.getAttribute("name")),
    placeholder: trim(el.getAttribute("placeholder")),
    ariaLabel: trim(el.getAttribute("aria-label")),
    role: trim(el.getAttribute("role")),
    className: trim(el.className, 160),
    text: trim(el.innerText || el.textContent, 80),
    disabled: !!el.disabled,
    visible: visible(el),
  });

  const collect = (selector, limit = 120) => {
    try {
      return Array.from(document.querySelectorAll(selector)).slice(0, limit).map(describeControl);
    } catch (e) { return []; }
  };

  const counts = {};
  for (const selector of ["input", "select", "textarea", "button", "form", "iframe", "table", "tr", "[role=combobox]", "[role=table]", "[attr-field-id]"]) {
    try { counts[selector] = document.querySelectorAll(selector).length; } catch (e) { counts[selector] = -1; }
  }

  /** 按关键词找候选区块：给人工推导选择器用，不自动写进契约。 */
  const keywordAreas = {};
  const KEYS = {
    category: ["类目", "选择类目", "搜索类目", "以图发品", "搜索发品"],
    title: ["商品标题", "标题"],
    props: ["属性", "必填属性", "商品属性"],
    saleProps: ["销售属性", "颜色分类", "尺码", "规格"],
    priceStock: ["价格", "库存", "一口价"],
    freight: ["运费", "物流", "发货", "模板"],
    media: ["主图", "详情", "图片"],
    submit: ["提交", "发布", "保存草稿", "放入仓库"],
  };
  for (const [key, words] of Object.entries(KEYS)) {
    const hits = [];
    const nodes = document.querySelectorAll("div,section,label,span,button,th,td,h1,h2,h3,h4");
    let scanned = 0;
    for (const node of nodes) {
      scanned += 1;
      if (scanned > 20000) break;
      const text = trim(node.innerText || node.textContent, 200);
      if (!text) continue;
      if (!words.some((word) => text.includes(word))) continue;
      // 只保留「不太大」的节点，避免整页 body 命中每一个关键词
      const childCount = node.children ? node.children.length : 0;
      if (childCount > 30) continue;
      hits.push({
        tag: node.tagName.toLowerCase(),
        id: trim(node.id),
        className: trim(node.className, 160),
        attrFieldId: trim(node.getAttribute("attr-field-id")),
        dataTestId: trim(node.getAttribute("data-testid")),
        text: text.slice(0, 120),
        visible: visible(node),
      });
      if (hits.length >= 25) break;
    }
    keywordAreas[key] = hits;
  }

  /** 带 attr-field-id 的字段容器：淘宝表单常用这个属性标识字段，值得单独列出。 */
  const fieldContainers = [];
  try {
    for (const node of document.querySelectorAll("[attr-field-id]")) {
      fieldContainers.push({
        attrFieldId: trim(node.getAttribute("attr-field-id")),
        tag: node.tagName.toLowerCase(),
        className: trim(node.className, 120),
        visible: visible(node),
      });
      if (fieldContainers.length >= 80) break;
    }
  } catch (e) { /* 选择器不支持时留空，不猜 */ }

  return {
    href: location.href,
    title: document.title,
    readyState: document.readyState,
    isLoginPage: /login\.taobao\.com|login\.tmall\.com/.test(location.href),
    hasWorkbenchKeyword: /发布商品|商品发布|选择类目|以图发品|搜索发品/.test(document.body ? document.body.innerText : ""),
    hasBlockingOverlayGuess: !!document.querySelector('[class*="dialog"]:not([style*="display: none"]), [class*="modal"]:not([style*="display: none"])'),
    counts,
    controls: {
      inputs: collect("input", 60),
      selects: collect("select", 30),
      textareas: collect("textarea", 20),
      buttons: collect("button, [role=button], a[class*='btn']", 60),
    },
    fieldContainers,
    keywordAreas,
    bodyTextSample: trim(document.body ? document.body.innerText : "", 1200),
  };
})()`;

/**
 * 轻量指纹：用来判断「页面是不是换了一步」。
 *
 * 组合四个维度，任意一个变化就算换步：
 *   1. URL（含 hash —— SPA 换步常常只改 hash）
 *   2. 表单控件数量（类目页与填写页差得很远）
 *   3. `attr-field-id` 集合（填写页每一步出现的字段不一样）
 *   4. 可见标签文本的简单校验和（兜住「路由没变但内容变了」）
 */
export const FINGERPRINT_EXPRESSION = String.raw`(() => {
  const trim = (value, limit = 60) => String(value == null ? "" : value).replace(/\s+/g, " ").trim().slice(0, limit);
  const count = (selector) => {
    try { return document.querySelectorAll(selector).length; } catch (e) { return -1; }
  };
  const fieldIds = [];
  try {
    for (const node of document.querySelectorAll("[attr-field-id]")) {
      const id = trim(node.getAttribute("attr-field-id"));
      if (id) fieldIds.push(id);
      if (fieldIds.length >= 200) break;
    }
  } catch (e) { /* 忽略 */ }

  // 可见标签文本的校验和：只取体积小、变化敏感的片段
  let checksum = 0;
  let sampled = 0;
  const nodes = document.querySelectorAll("label,th,h1,h2,h3,h4,legend");
  for (const node of nodes) {
    if (sampled >= 120) break;
    const text = trim(node.innerText || node.textContent, 40);
    if (!text) continue;
    sampled += 1;
    for (let i = 0; i < text.length; i += 1) {
      checksum = (checksum * 31 + text.charCodeAt(i)) % 2147483647;
    }
  }

  return {
    href: location.href,
    title: document.title,
    inputCount: count("input"),
    selectCount: count("select"),
    buttonCount: count("button"),
    tableRowCount: count("table tr"),
    fieldIdCount: fieldIds.length,
    fieldIds: fieldIds.slice(0, 60),
    labelChecksum: checksum,
    labelSamples: sampled,
  };
})()`;

/** 把指纹压成一个短字符串，用来做「变了没有」的比较。 */
export function fingerprintKey(fingerprint) {
  if (!fingerprint) return "unknown";
  return [
    fingerprint.href,
    fingerprint.inputCount,
    fingerprint.selectCount,
    fingerprint.buttonCount,
    fingerprint.tableRowCount,
    fingerprint.fieldIdCount,
    fingerprint.labelChecksum,
    (fingerprint.fieldIds || []).join("|"),
  ].join("::");
}
