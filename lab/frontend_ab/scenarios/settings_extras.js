// 设置页额外场景：
//  1) 「高级集成」「关于」在不同 Tauri 运行环境下的文案（用假的 __TAURI_INTERNALS__.invoke 提供 get_app_info / 版本）
//  2) 路由参数 ?tab= 选择初始 Tab
//  3) 设置加载失败 → 重试加载
(() => {
  window.__scn = window.__scn || {};
  window.__scn.settings_extras = async function (phase) {
    const H = window.__H;
    // 页面可见时 App.vue 会因 focus / visibilitychange 反复静默刷新商品列表，插进请求日志；
    // 让页面自认「不可见」，结果就不再取决于浏览器窗格当前有没有显示出来。
    H.quiet();
    const ev = [];
    const note = (s) => ev.push(s);

    if (!window.__toastObserver) {
      window.__toastLog = [];
      window.__toastObserver = new MutationObserver((muts) => {
        for (const m of muts) {
          for (const n of m.addedNodes) {
            if (n.nodeType !== 1) continue;
            const els = n.matches && n.matches(".el-message") ? [n] : [...(n.querySelectorAll ? n.querySelectorAll(".el-message") : [])];
            els.forEach((e) => window.__toastLog.push(H.text(e)));
          }
        }
      });
      window.__toastObserver.observe(document.body, { childList: true, subtree: true });
    }
    const flushToasts = (label) => note(`[toast] ${label}: ${JSON.stringify(window.__toastLog.splice(0))}`);
    const dump = async (name) => { note(await H.dump(`${phase}_${name}.txt`, ".settings-page")); };
    const tab = async (name) => { await H.click(H.q(`#tab-${name}`), name); await H.sleep(450); };
    const btn = (root, text) => H.byText("button", text, root || document);
    const waitPanel = async () => {
      await H.waitFor(() => H.q(".settings-panel") && !H.q(".settings-panel .el-loading-mask"), { label: "设置面板" });
      await H.sleep(1200);
    };
    const nav = async (hash) => {
      location.hash = hash;
      await H.sleep(600);
    };
    const remountSettings = async (query = "") => {
      await nav("#/");
      await H.waitFor(() => H.q(".product-manager"), { label: "主页" });
      await H.sleep(500);
      await nav("#/settings" + query);
      await waitPanel();
    };

    // ---- 假 Tauri：get_app_info / 版本 / 其它命令 ----
    const variants = {
      dev_node: {
        name: "Douyin Sock Publisher", version: "4.0.30", platform: "windows", arch: "x86_64",
        backend_url: "http://127.0.0.1:5001", runtime_mode: "development",
        app_dir: "C:\\proj\\tauri-app", workspace_root: "C:\\proj", resource_root: null,
        mcp_server_dir: "C:\\proj\\O'Brien\\mcp-server", mcp_server_entry: "C:\\proj\\O'Brien\\mcp-server\\server.js",
        mcp_readme_path: "C:\\proj\\mcp-server\\README.md", skill_dir: "C:\\proj\\skills\\douyin-publisher-mcp",
        mcp_http_endpoint: "http://127.0.0.1:3300/mcp", mcp_executable_path: null, bundled_node_path: null,
        mcp_server_exists: true, mcp_server_entry_exists: true, mcp_readme_exists: true, skill_dir_exists: true,
        mcp_executable_exists: false, bundled_node_exists: false, preferred_mcp_launch_mode: "node",
      },
      packaged_exe: {
        name: "Douyin Sock Publisher", version: "4.0.30", platform: "windows", arch: "x86_64",
        backend_url: "http://127.0.0.1:5001", runtime_mode: "packaged",
        app_dir: "C:\\Program Files\\App", workspace_root: "C:\\Program Files\\App", resource_root: "C:\\Program Files\\App\\resources",
        mcp_server_dir: "C:\\Program Files\\App\\resources\\mcp-server", mcp_server_entry: "C:\\Program Files\\App\\resources\\mcp-server\\server.js",
        mcp_readme_path: "C:\\Program Files\\App\\resources\\mcp-server\\README.md", skill_dir: "C:\\Program Files\\App\\resources\\skills\\douyin-publisher-mcp",
        mcp_http_endpoint: "http://127.0.0.1:3300/mcp", mcp_executable_path: "C:\\Program Files\\App\\resources\\mcp-server.exe",
        bundled_node_path: "C:\\Program Files\\App\\resources\\mcp-runtime\\node.exe",
        mcp_server_exists: true, mcp_server_entry_exists: true, mcp_readme_exists: true, skill_dir_exists: true,
        mcp_executable_exists: true, bundled_node_exists: true, preferred_mcp_launch_mode: "exe",
      },
      packaged_bundled_node: {
        name: "Douyin Sock Publisher", version: "4.0.30", platform: "windows", arch: "x86_64",
        backend_url: "http://127.0.0.1:5001", runtime_mode: "packaged",
        app_dir: "D:\\App", workspace_root: "D:\\App", resource_root: "D:\\App\\res",
        mcp_server_dir: "D:\\App\\res\\mcp-server", mcp_server_entry: "D:\\App\\res\\mcp-server\\server.js",
        mcp_readme_path: "D:\\App\\res\\mcp-server\\README.md", skill_dir: "D:\\App\\res\\skills\\douyin-publisher-mcp",
        mcp_http_endpoint: "http://127.0.0.1:3300/mcp", mcp_executable_path: null, bundled_node_path: "D:\\App\\res\\mcp-runtime\\node.exe",
        mcp_server_exists: true, mcp_server_entry_exists: true, mcp_readme_exists: true, skill_dir_exists: false,
        mcp_executable_exists: false, bundled_node_exists: true, preferred_mcp_launch_mode: "node",
      },
      nothing: {
        name: "Douyin Sock Publisher", version: "4.0.30", platform: "windows", arch: "x86_64",
        backend_url: "", runtime_mode: "development",
        app_dir: "", workspace_root: "", resource_root: null,
        mcp_server_dir: "", mcp_server_entry: "", mcp_readme_path: "", skill_dir: "",
        mcp_http_endpoint: "", mcp_executable_path: null, bundled_node_path: null,
        mcp_server_exists: false, mcp_server_entry_exists: false, mcp_readme_exists: false, skill_dir_exists: false,
        mcp_executable_exists: false, bundled_node_exists: false, preferred_mcp_launch_mode: "node",
      },
    };
    window.__appInfoVariant = "dev_node";
    window.__TAURI_INTERNALS__ = {
      invoke: async (cmd) => {
        if (cmd === "get_app_info") return variants[window.__appInfoVariant];
        if (cmd === "plugin:app|version") return "4.0.30-test";
        if (cmd === "plugin:updater|check") return null;
        throw new Error(`stub: 未实现的命令 ${cmd}`);
      },
      transformCallback: () => 0,
      metadata: { currentWindow: { label: "main" }, currentWebview: { label: "main", windowLabel: "main" } },
    };

    // ---- 1. 各运行环境下的「高级集成」/「关于」----
    for (const name of Object.keys(variants)) {
      window.__appInfoVariant = name;
      await remountSettings();
      await tab("mcp");
      await dump(`mcp_${name}`);
      await tab("about");
      await dump(`about_${name}`);
      if (name === "dev_node") {
        await H.click(btn(H.q("#pane-about"), "检查更新"), "检查更新");
        await H.sleep(900);
        flushToasts("检查更新(假 Tauri: 无新版本)");
      }
    }

    // ---- 2. 路由参数 ?tab= ----
    for (const q of ["?tab=automation", "?tab=model", "?tab=about", "?tab=unknown"]) {
      await remountSettings(q);
      note(`[route ${q}] active=${H.text(H.q(".el-tabs__item.is-active"))} title=${H.text(H.q(".header-text h1"))}`);
      await dump(`route_${q.replace(/[^a-z]/g, "")}`);
    }

    // ---- 3. 设置加载失败 → 重试 ----
    await H.ctl("mock", { settings_fail: true });
    await remountSettings();
    flushToasts("加载失败");
    note(`[footer-loadfail] ${H.text(H.q(".settings-footer"))}`);
    note(`[save-disabled] ${btn(H.q(".settings-footer"), "保存设置").disabled}`);
    await dump("loadfail");
    await H.click(btn(H.q(".settings-footer"), "保存设置"), "保存(禁用中)");
    await H.sleep(300);
    await H.ctl("mock", { settings_fail: false });
    await H.click(btn(H.q(".settings-footer"), "重试加载"), "重试加载");
    await H.sleep(1500);
    flushToasts("重试加载");
    note(`[footer-after-retry] ${H.text(H.q(".settings-footer"))}`);
    await dump("after_retry");

    note(`[console] ${JSON.stringify(window.__consoleLog)}`);
    const info = await H.save(`${phase}_settings_extras_events.txt`, ev.join("\n"));
    const logInfo = await H.ctl(`save-log?name=${phase}_settings_extras_requests.jsonl`);
    return `events=${ev.length} saved=${JSON.stringify(info)} log=${JSON.stringify(logInfo)} dpr=${devicePixelRatio}`;
  };
})();
