// 验证专用的 Vite 配置包装（用法见 README.md；不属于产品代码，不进安装包）。
//
// 前端把后端地址写死成 http://127.0.0.1:5001，而 5001 是真实桌面应用的 Sidecar 端口——
// 验证时它可能正在运行，里面是用户的真实数据，验证工具绝不能占用或碰它。
// 所以验证用的前端开发服务器用这个配置启动：不改被测源码，只在开发服务器吐给浏览器的模块里，
// 把 127.0.0.1:5001 改写成验证代理的端口（环境变量 AB_PROXY_PORT，默认 5003）。
//
// 注意：
// 1. 扩展名必须是 .mts：本文件所在目录没有 package.json（"type": "module"），.ts 会被当成 CJS 加载，
//    而 @vitejs/plugin-vue 等依赖在 CJS 下取不到 default（实测：`import_vite2.default is not a function`）。
// 2. 本文件不在前端工程目录里，解析不到那边的 node_modules，所以这里不能 `import ... from "vite"`
//    （下面全是普通对象）；`../../tauri-app/vite.config` 会被一起打包进来，它自己的依赖仍从 tauri-app 解析。
// 「原版」前端副本里（ab.ps1 orig 生成）这个路径会被换成 ./vite.config。
import base from "../../tauri-app/vite.config";

const proxyPort = process.env.AB_PROXY_PORT || "5003";

const rewriteBackendPort = {
  name: "ab-rewrite-backend-port",
  enforce: "pre" as const,
  transform(code: string, id: string) {
    if (!id.includes("/src/") || !code.includes("127.0.0.1:5001")) return null;
    return { code: code.split("127.0.0.1:5001").join(`127.0.0.1:${proxyPort}`), map: null };
  },
};

export default { ...base, plugins: [rewriteBackendPort, ...(base.plugins ?? [])] };
