// 最小 DOM 桩件：把真机读到的字段形态复刻出来，供 REQUIRED_FIELDS 行为级验证使用。
//
// 只实现被验证脚本用到的 API：querySelector / querySelectorAll / getBoundingClientRect /
// getComputedStyle / getAttribute / textContent / className。
//
// 关键细节（错一个就会得到假结果 ✗）：真机的"行"里，标签与值分属不同元素，
// innerText 里是**两行** → 归一化后标签是独立的短文本。所以标签必须包在自己的
// 元素里并带尾随换行，否则整行文本会被当成标签（实测会取成 `适用性别通用`）。

export class El {
  constructor(tag, attrs = {}, text = '') {
    this.tagName = String(tag).toUpperCase();
    this.attrs = { ...attrs };
    this.src = this.attrs.src || '';
    // 表单控件的值是真机判据之一（`input.value`），必须以**属性**形式暴露
    this.value = this.attrs.value !== undefined ? this.attrs.value : '';
    this._text = text;
    this.children = [];
    this.parentElement = null;
  }

  get className() { return this.attrs.class || ''; }

  get textContent() {
    return this.children.reduce((acc, child) => acc + child.textContent, '') + this._text;
  }

  getAttribute(name) { return this.attrs[name] ?? null; }

  getBoundingClientRect() { return { x: 10, y: 10, width: 100, height: 30 }; }

  querySelectorAll(selector) {
    const out = [];
    const walk = (node) => {
      for (const child of node.children) {
        if (matches(child, selector)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }

  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }

  append(...nodes) {
    for (const node of nodes) { node.parentElement = this; this.children.push(node); }
    return this;
  }
}

export function matches(node, selector) {
  const parts = selector.split(',').map(part => part.trim());
  return parts.some(part => {
    if (part.includes(' ')) {                       // 后代选择器 "A B"
      const [ancestor, descendant] = part.split(/\s+/);
      let parent = node.parentElement;
      while (parent) {
        if (matches(parent, ancestor)) return matches(node, descendant);
        parent = parent.parentElement;
      }
      return false;
    }
    const attr = part.match(/^([a-zA-Z]+)?\[class\*="([^"]+)"\]$/);
    if (attr) {
      const [, tag, klass] = attr;
      if (tag && node.tagName !== tag.toUpperCase()) return false;
      return node.className.includes(klass);
    }
    const tagOnly = part.match(/^([a-zA-Z]+)$/);
    if (tagOnly) return node.tagName === tagOnly[1].toUpperCase();
    return false;
  });
}

/** 造一行：`row(标签元素, 控件元素...)` — 标签必须**是第一个参数**（它会被包进自己的元素）。
 *
 * ⚠️ 别把 required 标记当成第一个参数传进来（踩过 ✗）：那样标记会被当成"标签"
 * 包进 labelWrap，真正标记反而不在行内 → `querySelectorAll('[class*="required-icon"]')` 读到 0 个。
 */
export function row(...cells) {
  const container = new El('div');
  const [label, ...rest] = cells;
  container.append(new El('div', {}, `${label.textContent}\n`), ...rest);
  return container;
}

/** 造页面：每个"行"都自带一个 `required-icon` 标记（真机就是这样）。
 *
 * 标记的两个细节都按真机复刻（错一个就会让标签提取失真 ✗）：
 * 1. 它是**空文本元素**（所以 innerText 里读不到 `*`，必须按 class 找）；
 * 2. 它**紧跟在标签之后**、位于标签的包裹元素内 —— 这样它不会把标签与值连成一体，
 *    标签提取（`t.length <= 14` 的短文本）才拿得到真标签。
 */
export function buildBody(rows) {
  const body = new El('div');
  for (const cells of rows) {
    const [label, ...rest] = cells;
    const labelWrap = new El('div', {}, `${label.textContent}\n`);
    labelWrap.append(new El('span', { class: 'd-required-icon required-icon' }, ''));
    const container = new El('div');
    container.append(labelWrap, ...rest);
    body.append(container);
  }
  return body;
}

/** 把桩件装到全局，让被验证的脚本能像在页面里一样取到 document / getComputedStyle。 */
export function install(body) {
  globalThis.document = { querySelectorAll: (selector) => body.querySelectorAll(selector) };
  globalThis.getComputedStyle = () => ({ display: 'block', visibility: 'visible' });
  globalThis.window = {};
}
