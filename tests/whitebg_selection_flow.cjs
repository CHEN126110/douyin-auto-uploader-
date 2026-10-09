// 实际 API + Pinia 源码：模拟 HTTP 回执，绝不修改用户数据库。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const frontend = path.resolve(__dirname, '../tauri-app');
const vue = require(path.join(frontend, 'node_modules/vue'));
const ts = require(path.join(frontend, 'node_modules/typescript'));
function load(relative, dependencies) {
  const code = ts.transpileModule(fs.readFileSync(path.join(frontend, relative), 'utf8'), {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020},
  }).outputText;
  const module = {exports: {}};
  vm.runInNewContext(code, {module, exports: module.exports, Map, Set, Date, URLSearchParams,
    console: {log() {}, error() {}}, require(name) {
      if (!(name in dependencies)) throw Error('未配置依赖 ' + name);
      return dependencies[name];
    },
  });
  return module.exports;
}
function fixture(respond) {
  const calls = [];
  const http = {put: async (url, payload) => {calls.push({url, payload}); return respond(url, payload);},
    interceptors: {response: {use() {}}}};
  const api = load('src/services/api.ts', {
    axios: {__esModule: true, default: {create: () => http}}, '@tauri-apps/api/core': {}, '@/types': {},
  });
  const store = load('src/stores/productStore.ts', {
    vue, pinia: {defineStore: (_id, setup) => setup}, 'element-plus': {}, '@/services/api': api,
  }).useProductStore();
  store.mediaListing.value = {record_id: 7, white_bg_selection: {path: '', valid: true, error: ''}};
  store.currentProduct.value = {id: 7, white_bg_path: '', content: []};
  return {store, calls};
}
const answer = (path, recordId = 7) => ({success: true, data: {
  record_id: recordId, selection: {path, valid: true, error: ''}, update_time: '2026-10-09 22:00', record_revision: 'a'.repeat(64),
}});

test('按当前商品保存完整相对路径，并更新界面选择', async () => {
  const f = fixture((_url, payload) => answer(payload.path));
  assert.equal(await f.store.setWhiteBgSelection(7, '白底图/浅灰 色.png'), true);
  assert.equal(f.calls[0].url, '/api/products/7/media/white-background');
  assert.equal(f.calls[0].payload.path, '白底图/浅灰 色.png');
  assert.equal(f.store.mediaListing.value.white_bg_selection.path, '白底图/浅灰 色.png');
  assert.equal(f.store.currentProduct.value.white_bg_path, '白底图/浅灰 色.png');
});

test('恢复自动发送空路径，保存后清除人工选择', async () => {
  const f = fixture((_url, payload) => answer(payload.path));
  f.store.mediaListing.value.white_bg_selection.path = '白底图/旧图.png';
  assert.equal(await f.store.setWhiteBgSelection(7, ''), true);
  assert.equal(f.calls[0].payload.path, '');
  assert.equal(f.store.mediaListing.value.white_bg_selection.path, '');
});

test('请求未完成时重复点击不会重复保存', async () => {
  let resolve;
  const f = fixture(() => new Promise(done => {resolve = done;}));
  const pending = f.store.setWhiteBgSelection(7, '自选.png');
  assert.equal(await f.store.setWhiteBgSelection(7, '另一张.png'), false);
  assert.equal(f.calls.length, 1);
  resolve(answer('自选.png'));
  assert.equal(await pending, true);
  assert.equal(f.store.whiteBgSaving.value, false);
});

test('保存期间切换商品，旧回执不能覆盖新商品界面', async () => {
  let resolve;
  const f = fixture(() => new Promise(done => {resolve = done;}));
  const pending = f.store.setWhiteBgSelection(7, '自选.png');
  f.store.mediaListing.value = {record_id: 8, white_bg_selection: {path: '商品八.png'}};
  f.store.currentProduct.value = {id: 8, white_bg_path: '商品八.png'};
  resolve(answer('自选.png'));
  assert.equal(await pending, true);
  assert.equal(f.store.mediaListing.value.white_bg_selection.path, '商品八.png');
  assert.equal(f.store.currentProduct.value.white_bg_path, '商品八.png');
});

test('后端拒绝修改时保留旧选择，并显示真实失败原因', async () => {
  const f = fixture(() => {throw {response: {data: {msg: '该商品正在发布'}}};});
  f.store.mediaListing.value.white_bg_selection.path = '原图.png';
  assert.equal(await f.store.setWhiteBgSelection(7, '新图.png'), false);
  assert.equal(f.store.lastActionError.value, '该商品正在发布');
  assert.equal(f.store.mediaListing.value.white_bg_selection.path, '原图.png');
  assert.equal(f.store.whiteBgSaving.value, false);
});

test('不匹配的回执不能显示为保存成功', async () => {
  const f = fixture(() => answer('错误图片.png', 8));
  assert.equal(await f.store.setWhiteBgSelection(7, '自选.png'), false);
  assert.match(f.store.lastActionError.value, /回执与当前操作不一致/);
  assert.equal(f.store.mediaListing.value.white_bg_selection.path, '');
});
