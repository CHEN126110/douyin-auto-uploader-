// 行为级验证：把 page_scripts.REQUIRED_FIELDS 那段**真实 JS** 放进最小 DOM 桩件里跑。
//
// 为什么需要它（2026-10-14 真机踩过 ✗）：旧的"是否已填"判据只看 input.value 与
// "请选择"，于是四类**已填**字段被误报成未填 —— 字符串包含断言完全抓不到这类 bug
// （脚本里确实有"请选择"，也有 required-icon）。
//
// 跑法：node run-required-fields-check.mjs <required-fields.js>
//   输入文件内容是一个 JSON 字符串字面量（REQUIRED_FIELDS 源码）。
// 输出：{"failed": [...], "observed": {...}}；有失败项时退出码 1。

import { readFileSync } from 'node:fs';
import { El, buildBody, install } from './dom-stub.mjs';

const sourceFile = process.argv[2];
if (!sourceFile) {
  console.error('用法: node run-required-fields-check.mjs <required-fields.js>');
  process.exit(2);
}
const REQUIRED_FIELDS = JSON.parse(readFileSync(sourceFile, 'utf8'));

function runCase(rows) {
  install(buildBody(rows));
  // eslint-disable-next-line no-eval
  return eval(REQUIRED_FIELDS);
}

// ---- 真机实测的六种形态（2026-10-14 现场读数） ---------------------------

const cases = {
  // ① 单选框显示具体值（真机：适用性别=通用 / 上市时间=2024年秋冬季）
  single_select_filled: () => [[
    new El('span', {}, '适用性别'),
    new El('div', { class: 'd-select' }, '通用'),
  ]],
  // ② 多选框：select 文本把占位与已选值拼在一起（"请选择春季秋季秋冬"），但有 tag 元素
  multi_select_filled: () => {
    const select = new El('div', { class: 'd-select' });
    const tags = new El('div', { class: 'd-select-tags' });
    tags.append(new El('span', { class: 'd-tag' }, '春季'),
                new El('span', { class: 'd-tag' }, '秋季'),
                new El('span', { class: 'd-tag' }, '秋冬'));
    select.append(new El('span', { class: 'd-select-placeholder' }, '请选择'), tags);
    return [[new El('span', {}, '适用季节'), select]];
  },
  // ③ 图片行已落图：行内有 img[src]，文案仍残留"上传中..."
  image_row_filled: () => {
    const cell = new El('div', {}, '商品主图上传中...');
    cell.append(new El('img', { src: 'https://ros-preview.xhscdn.com/arkgoods/x.jpg' }));
    return [[new El('span', {}, '商品主图'), cell]];
  },
  // ④ 单选框未选：显示占位"请选择"、无 tag
  single_select_unfilled: () => [[
    new El('span', {}, '售后服务'),
    new El('div', { class: 'd-select' }, '请选择'),
  ]],
  // ⑤ 图片行未传图：没有 img
  image_row_unfilled: () => [[
    new El('span', {}, '商品主图'),
    new El('div', {}, '上传主图上传图片'),
  ]],
  // ⑥ 输入框有值 / 空值
  input_filled_and_empty: () => [[
    new El('span', {}, '商品标题'),
    new El('input', { type: 'text', value: '秋冬条纹纯棉中筒袜' }),
  ], [
    new El('span', {}, '货号'),
    new El('input', { type: 'text', value: '' }),
  ]],
};

const expected = {
  single_select_filled: { unfilled: [], filled: ['适用性别'] },
  multi_select_filled: { unfilled: [], filled: ['适用季节'] },
  image_row_filled: { unfilled: [], filled: ['商品主图'] },
  single_select_unfilled: { unfilled: ['售后服务'], filled: [] },
  image_row_unfilled: { unfilled: ['商品主图'], filled: [] },
  input_filled_and_empty: { unfilled: ['货号'], filled: ['商品标题'] },
};

const failed = [];
const observed = {};
for (const [name, makeRows] of Object.entries(cases)) {
  const result = runCase(makeRows());
  observed[name] = result;
  const want = expected[name];
  const gotUnfilled = [...(result.unfilled || [])].sort();
  const wantUnfilled = [...want.unfilled].sort();
  const gotFilled = [...(result.filled || [])].sort();
  const wantFilled = [...want.filled].sort();
  if (JSON.stringify(gotUnfilled) !== JSON.stringify(wantUnfilled)
      || JSON.stringify(gotFilled) !== JSON.stringify(wantFilled)) {
    failed.push({ case: name, want, got: { unfilled: gotUnfilled, filled: gotFilled } });
  }
}

console.log(JSON.stringify({ failed, observed }, null, 2));
process.exit(failed.length ? 1 : 0);
