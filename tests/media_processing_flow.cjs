// 图片处理迁移的实际 Vue 组件交互测试；接口使用隔离桩，不运行模型或写商品文件。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const test = require('node:test');
const frontend = path.resolve(__dirname, '../tauri-app');
const vue = require(path.join(frontend, 'node_modules/vue'));
const ts = require(path.join(frontend, 'node_modules/typescript'));
const {parse, compileScript} = require(path.join(frontend, 'node_modules/@vue/compiler-sfc'));

function component(name, props, dependencies, t) {
  const source = fs.readFileSync(path.join(frontend, 'src/components', name + '.vue'), 'utf8');
  const {descriptor} = parse(source);
  const code = ts.transpileModule(compileScript(descriptor, {id: 'test-' + name}).content,
    {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText;
  const module = {exports: {}}, unmount = [], events = [], scope = vue.effectScope();
  vm.runInNewContext(code, {module, exports: module.exports, console, Set, Date,
    setTimeout: callback => setImmediate(callback),
    require(name) {
      if (name === 'vue') return {...vue, onUnmounted: callback => unmount.push(callback)};
      if (name in dependencies) return dependencies[name];
      throw Error('未配置依赖：' + name);
    },
  });
  const state = scope.run(() => module.exports.default.setup(props, {
    expose() {}, emit: (...args) => events.push(args),
  }));
  const dispose = () => { unmount.forEach(fn => fn()); scope.stop(); };
  t.after(dispose);
  return {state, props, events, dispose};
}

const deferred = () => {
  let resolve;
  return {promise: new Promise(accept => {resolve = accept;}), resolve: value => resolve(value)};
};
const ready = {success: true, data: {ready: true}};
const finished = (recordId = 7) => ({success: true, data: {
  task_id: 'task-7', record_id: recordId, status: 'success', progress: 100, message: '处理完成',
  result: {items: [{name: '白色', white_ok: true, square_ok: true, warnings: []}], fallback_items: []},
}});

function white(t, overrides = {}, extraProps = {}) {
  const calls = [], notices = [], alerts = [];
  const api = {
    getWhiteBgStatus: async () => { calls.push(['status']); return ready; },
    startWhiteBg: async options => { calls.push(['start', options]); return {success: true, data: {task_id: 'task-7'}}; },
    getWhiteBgTask: async id => { calls.push(['poll', id]); return finished(); },
    whiteBgImageUrl: path => '/fixture-image/' + path,
    ...overrides,
  };
  const props = vue.reactive({recordId: 7, recordName: '商品七', active: true, disabled: false, ...extraProps});
  return {...component('WhiteBgPanel', props, {
    '@/services/api': {api},
    'element-plus': {ElMessage: {
      warning: text => notices.push(text), success: text => notices.push(text), error: text => notices.push(text),
    }, ElMessageBox: {alert: async (...args) => alerts.push(args)}},
  }, t), calls, notices, alerts, api};
}

test('处理当前图片窗口对应的商品，完成事件包含商品 ID', async t => {
  const f = white(t);
  await f.state.start();
  assert.equal(f.calls.find(call => call[0] === 'start')[1].recordId, 7);
  assert.equal(f.events[0][0], 'done');
  assert.equal(f.events[0][1].recordId, 7);
  assert.equal(f.events[0][1].successCount, 1);
  assert.equal(f.state.taskRecordName.value, '商品七');
  assert.equal(f.state.resultVisible.value, true);
});

test('环境检查尚未返回时重复点击，只启动一次任务', async t => {
  const pending = deferred(); let checks = 0;
  const f = white(t, {getWhiteBgStatus: () => { checks++; return pending.promise; }});
  const first = f.state.start();
  await f.state.start();
  assert.equal(f.state.running.value, true);
  pending.resolve(ready);
  await first;
  assert.equal(checks, 1);
  assert.equal(f.calls.filter(call => call[0] === 'start').length, 1);
});

for (const change of ['switch', 'close', 'disable', 'unmount']) {
  test(`启动前${change}，不会把任务发给另一件商品或在关闭后启动`, async t => {
    const pending = deferred();
    const f = white(t, {getWhiteBgStatus: () => pending.promise});
    const run = f.state.start();
    if (change === 'switch') f.props.recordId = 8;
    if (change === 'close') f.props.active = false;
    if (change === 'disable') f.props.disabled = true;
    if (change === 'unmount') f.dispose();
    pending.resolve(ready);
    await run;
    assert.equal(f.calls.length, 0);
    assert.equal(f.state.running.value, false);
  });
}

test('启动后切换商品，完成结果保留原商品归属且不弹出', async t => {
  const f = white(t, {getWhiteBgTask: async () => {
    f.props.recordId = 8; f.props.recordName = '商品八';
    await vue.nextTick();
    return finished();
  }});
  await f.state.start();
  assert.equal(f.events[0][1].recordId, 7);
  assert.equal(f.state.taskRecordName.value, '商品七');
  assert.equal(f.state.resultVisible.value, false);
  assert.equal(f.state.canShowResult.value, false);
});

test('任务在关闭窗口后完成，重新打开同一商品可查看结果', async t => {
  const f = white(t, {getWhiteBgTask: async () => {
    f.props.active = false; await vue.nextTick(); return finished();
  }});
  await f.state.start();
  assert.equal(f.state.resultVisible.value, false);
  assert.equal(f.state.hasResult.value, true);
  f.props.active = true;
  await vue.nextTick();
  assert.equal(f.state.canShowResult.value, true);
  assert.equal(f.state.resultVisible.value, false);
});

test('模型缺失只显示真实提示，不启动生成或报告成功', async t => {
  const f = white(t, {getWhiteBgStatus: async () => ({success: true, data: {ready: false}})});
  await f.state.start();
  assert.equal(f.alerts.length, 1);
  assert.equal(f.calls.length, 0);
  assert.equal(f.events.length, 0);
  assert.equal(f.state.running.value, false);
});

test('环境接口失败时显示具体原因，并恢复按钮', async t => {
  const f = white(t, {getWhiteBgStatus: async () => { throw {response: {data: {msg: '服务暂不可用'}}}; }});
  await f.state.start();
  assert.match(f.notices[0], /服务暂不可用/);
  assert.equal(f.calls.length, 0);
  assert.equal(f.state.running.value, false);
});

test('任务接口报告不存在时立即显示原因，不把失败当成等待', async t => {
  let reads = 0;
  const f = white(t, {getWhiteBgTask: async () => { reads++; return {success: false, msg: '任务不存在'}; }});
  await f.state.start();
  assert.equal(reads, 1);
  assert.match(f.notices[0], /任务不存在/);
  assert.equal(f.events.length, 0);
});

test('其他商品的任务回执不能显示为当前处理结果', async t => {
  const f = white(t, {getWhiteBgTask: async () => finished(8)});
  await f.state.start();
  assert.equal(f.events.length, 0);
  assert.equal(f.state.resultVisible.value, false);
  assert.match(f.notices[0], /任务不一致/);
});

test('完成后刷新当前目录，关闭或换商品后忽略旧任务的刷新', async t => {
  const loads = [];
  const store = vue.reactive({mediaListing: null, currentShopSession: null,
    loadMediaDirectory: async (...args) => loads.push(args), clearMediaListing() {},
  });
  const props = vue.reactive({modelValue: true, recordId: 7});
  const f = component('ProductMediaManager', props, {
    '@/stores/productStore': {useProductStore: () => store},
    '@/services/api': {api: {}, productMediaImageUrl() {}},
    '@/components/WhiteBgPanel.vue': {},
    '@element-plus/icons-vue': {}, 'element-plus': {},
  }, t);
  loads.length = 0;
  f.state.directory.value = 'SKU'; f.state.page.value = 2;
  await f.state.handleProcessingDone({recordId: 7});
  assert.deepEqual(loads, [[7, 'SKU', 100]]);
  props.modelValue = false; await vue.nextTick();
  await f.state.handleProcessingDone({recordId: 7});
  assert.equal(loads.length, 1);
  props.modelValue = true; props.recordId = 8; await vue.nextTick();
  loads.length = 0;
  await f.state.handleProcessingDone({recordId: 7});
  assert.equal(loads.length, 0);
});
