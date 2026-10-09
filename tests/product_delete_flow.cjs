// 真实 Pinia store 的删除结果处理；HTTP 使用隔离桩，不连接运行中的应用。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const frontend = path.resolve(__dirname, '../tauri-app');
const vue = require(path.join(frontend, 'node_modules/vue'));
const ts = require(path.join(frontend, 'node_modules/typescript'));
const source = fs.readFileSync(path.join(frontend, 'src/stores/productStore.ts'), 'utf8');
const javascript = ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
}}).outputText;

function fixture(api) {
  const module = {exports: {}};
  vm.runInNewContext(javascript, {module, exports: module.exports, Map, Set, Date,
    console: {log() {}, error() {}},
    require(name) {
      if (name === 'vue') return vue;
      if (name === 'pinia') return {defineStore: (_name, setup) => setup};
      if (name === 'element-plus') return {};
      if (name === '@/services/api') return {api};
      throw Error('Unexpected dependency: ' + name);
    },
  });
  const store = module.exports.useProductStore();
  store.products.value = [{id: 1, name: '采集商品'}, {id: 2, name: '手工商品'}];
  store.currentProductId.value = 1;
  store.currentProduct.value = {id: 1, content: []};
  return store;
}

test('单品删除失败保留列表，并显示后端 msg 的真实文件错误', async () => {
  const store = fixture({deleteProduct: async () => ({success: false, msg: '文件被占用'})});
  assert.equal(await store.deleteProduct(1), false);
  assert.equal(store.lastActionError.value, '文件被占用');
  assert.equal(store.products.value.length, 2);
  assert.equal(store.currentProductId.value, 1);
});

test('单品删除成功才移除列表及当前详情', async () => {
  const store = fixture({deleteProduct: async () => ({success: true})});
  assert.equal(await store.deleteProduct(1), true);
  assert.deepEqual(store.products.value.map(row => row.id), [2]);
  assert.equal(store.currentProductId.value, null);
  assert.equal(store.currentProduct.value, null);
});

test('清空部分失败后同步实际剩余商品，并保留失败原因', async () => {
  let reads = 0;
  const store = fixture({
    deleteAll: async () => ({success: false, msg: '已删除 1 个商品，第二个目录被占用'}),
    getProducts: async () => { reads++; return {success: true, products: [{id: 2}]}; },
  });
  assert.equal(await store.deleteAll(), false);
  assert.equal(reads, 1);
  assert.deepEqual(store.products.value.map(row => row.id), [2]);
  assert.equal(store.currentProduct.value, null);
  assert.match(store.lastActionError.value, /第二个目录被占用/);
});

test('清空请求结果未知时读取实际列表，不重复发送删除', async () => {
  let deletes = 0;
  const store = fixture({
    deleteAll: async () => { deletes++; throw Error('连接中断'); },
    getProducts: async () => ({success: true, products: []}),
  });
  assert.equal(await store.deleteAll(), false);
  assert.equal(deletes, 1);
  assert.equal(store.products.value.length, 0);
  assert.ok(store.lastActionError.value);
});

test('清空失败且同步失败时明确提示，不能伪装列表已清空', async () => {
  const store = fixture({
    deleteAll: async () => ({success: false, msg: '文件错误'}),
    getProducts: async () => ({success: false}),
  });
  assert.equal(await store.deleteAll(), false);
  assert.equal(store.products.value.length, 2);
  assert.match(store.lastActionError.value, /文件错误/);
  assert.match(store.lastActionError.value, /列表刷新失败/);
});

test('清空成功直接清理列表和详情', async () => {
  const store = fixture({deleteAll: async () => ({success: true})});
  assert.equal(await store.deleteAll(), true);
  assert.equal(store.products.value.length, 0);
  assert.equal(store.currentProductId.value, null);
  assert.equal(store.currentProduct.value, null);
  assert.equal(store.lastActionError.value, null);
});
