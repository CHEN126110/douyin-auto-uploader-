// 更新器真实源码回归：模拟 Tauri 与 HTTP，不停止实际后端、不安装程序。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const assert = require('node:assert/strict');
const ts = require('../tauri-app/node_modules/typescript');

function fixture(options = {}) {
  const calls = [];
  const errors = [];
  let running = options.running ?? true;
  const update = {
    version: '4.0.29', body: '更新验证',
    async download() { calls.push('download'); if (options.downloadError) throw Error('下载失败'); },
    async install() { calls.push('install'); if (options.installError) throw Error('安装失败'); },
  };
  const fetchReadiness = async url => {
    calls.push('readiness');
    assert.ok(url.endsWith('/internal/update-readiness'));
    return {ok: options.httpOK ?? true, json: async () => options.body ?? {success: true, data: {ready: true}}};
  };
  let stopCheckFlaps = options.stopCheckFlaps ?? 0;
  const dependencies = {
    '@/services/api': {
      api: {getUpdateReadiness: async () => {
        const response = await fetchReadiness('/internal/update-readiness');
        if (!response.ok) {
          const error = new Error('HTTP 500');
          error.response = {status: 500};
          throw error;
        }
        return response.json();
      }},
      apiErrorStatus: error => error.response?.status,
    },
    '@tauri-apps/plugin-updater': {check: options.check ?? (async () => update)},
    '@tauri-apps/plugin-process': {relaunch: async () => calls.push('relaunch')},
    '@tauri-apps/api/core': {invoke: async name => {
      if (name === 'check_backend_status') {
        if ((options.stopCheckError || stopCheckFlaps > 0) && !running) {
          if (stopCheckFlaps > 0) stopCheckFlaps--;
          throw Error('停止状态检查失败');
        }
        return running ? {success: true, status: 'ok'} : {success: false, status: 'offline'};
      }
      calls.push(name);
      if (name === 'stop_python_backend') running = false;
      if (name === 'start_python_backend') {
        if (options.restartError) throw Error('恢复失败');
        running = true;
      }
    }},
    'element-plus': {
      ElMessage: {error: msg => errors.push(msg), success() {}},
      ElMessageBox: {confirm: async () => { if (options.cancel) throw Error('cancel'); }},
      ElLoading: {service: () => ({setText() {}, close() {}})},
    },
  };
  // 虚拟时钟只随等待推进，避免 CI 的实际调度耗时挤占测试窗口；生产默认仍为 8 秒。
  let now = 0;
  const source = fs.readFileSync(path.join(__dirname, '../tauri-app/src/services/updater.ts'), 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020},
  }).outputText;
  const module = {exports: {}};
  vm.runInNewContext(code, {module, exports: module.exports, AbortSignal,
    Date: {now: () => now},
    require: name => dependencies[name],
    fetch: fetchReadiness,
    setTimeout: callback => {
      now += 200;
      setImmediate(callback);
    },
  });
  return {run: module.exports.checkForUpdate, calls, errors, running: () => running};
}

test('下载和空闲检查完成后才停止后端并安装', async () => {
  const f = fixture(); await f.run();
  assert.deepEqual(f.calls, ['download', 'readiness', 'stop_python_backend', 'install', 'relaunch']);
  assert.equal(f.errors.length, 0);
});
test('任务仍在运行时保留后端，不开始安装', async () => {
  const f = fixture({body: {success: true, data: {ready: false}}}); await f.run();
  assert.deepEqual(f.calls, ['download', 'readiness']);
  assert.equal(f.running(), true); assert.match(f.errors[0], /任务仍在进行/);
});
for (const [label, options] of [['接口失败', {httpOK: false}], ['返回无效', {body: {success: true}}]]) {
  test(label + '时不能假定空闲', async () => {
    const f = fixture(options); await f.run();
    assert.equal(f.running(), true); assert.ok(!f.calls.includes('install')); assert.equal(f.errors.length, 1);
  });
}
test('下载失败不停止后端', async () => {
  const f = fixture({downloadError: true}); await f.run();
  assert.deepEqual(f.calls, ['download']); assert.equal(f.running(), true);
});
test('安装失败恢复后端并报告失败', async () => {
  const f = fixture({installError: true}); await f.run();
  assert.equal(f.calls.at(-1), 'start_python_backend'); assert.equal(f.running(), true);
  assert.match(f.errors[0], /安装失败/); assert.ok(!f.calls.includes('relaunch'));
});
test('停止后健康接口短暂报错会等待离线再安装', async () => {
  const f = fixture({stopCheckFlaps: 2}); await f.run();
  assert.deepEqual(f.calls, ['download', 'readiness', 'stop_python_backend', 'install', 'relaunch']);
  assert.equal(f.errors.length, 0);
});
test('停止后的状态检查失败也恢复后端', async () => {
  const f = fixture({stopCheckError: true}); await f.run();
  assert.deepEqual(f.calls, ['download', 'readiness', 'stop_python_backend', 'start_python_backend']);
  assert.equal(f.running(), true);
  assert.ok(!f.calls.includes('install'));
  assert.match(f.errors[0], /停止状态检查失败/);
});
test('恢复后端失败明确提示用户', async () => {
  const f = fixture({installError: true, restartError: true}); await f.run();
  assert.match(f.errors[0], /后端恢复也失败/);
});
test('后端未启动仍能通过更新修复应用', async () => {
  const f = fixture({running: false}); await f.run();
  assert.deepEqual(f.calls, ['download', 'install', 'relaunch']);
});
test('取消更新没有下载、停止或安装行为', async () => {
  const f = fixture({cancel: true}); await f.run(); assert.deepEqual(f.calls, []);
});
test('检查进行中不会重复弹窗或安装，结束后允许再次检查', async () => {
  let resolve; let count = 0;
  const f = fixture({check: () => { count++; return new Promise(done => { resolve = done; }); }});
  const first = f.run(); await f.run(); assert.equal(count, 1);
  resolve(null); await first;
  const second = f.run(); assert.equal(count, 2); resolve(null); await second;
});
