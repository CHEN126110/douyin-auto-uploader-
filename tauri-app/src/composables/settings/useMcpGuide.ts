/**
 * 「高级集成」页的数据与文案：应用运行时路径（来自 Tauri 的 get_app_info）
 * 以及据此生成的 MCP 启动命令 / 客户端配置示例。
 *
 * 只读、不属于设置表单（不参与保存），所以由 McpTab 自己持有，不经过 SettingsPanel。
 */
import { computed, ref } from "vue";
import { BACKEND_URL, tauriCommands } from "@/services/api";
import type { AppInfo } from "@/types";

const defaultAppInfo: AppInfo = {
  name: "Douyin Sock Publisher",
  version: __APP_VERSION__,
  platform: "windows",
  arch: "x64",
  backend_url: BACKEND_URL,
  runtime_mode: "development",
  app_dir: "",
  workspace_root: "",
  resource_root: null,
  mcp_server_dir: "",
  mcp_server_entry: "",
  mcp_readme_path: "",
  skill_dir: "",
  mcp_http_endpoint: "http://127.0.0.1:3300/mcp",
  mcp_executable_path: null,
  bundled_node_path: null,
  mcp_server_exists: false,
  mcp_server_entry_exists: false,
  mcp_readme_exists: false,
  skill_dir_exists: false,
  mcp_executable_exists: false,
  bundled_node_exists: false,
  preferred_mcp_launch_mode: "node",
};

function escapeForPowerShell(path: string) {
  return path.replace(/'/g, "''");
}

function escapeForJson(path: string) {
  return path.replace(/\\/g, "\\\\");
}

export function useMcpGuide() {
  const appInfo = ref<AppInfo>({ ...defaultAppInfo });
  const loading = ref(false);
  const loadError = ref("");

  const backendUrl = computed(() => appInfo.value.backend_url || BACKEND_URL);
  const mcpServerPath = computed(() => appInfo.value.mcp_server_entry || "未检测到");
  const mcpHttpEndpoint = computed(
    () => appInfo.value.mcp_http_endpoint || "http://127.0.0.1:3300/mcp"
  );
  const skillPath = computed(() => appInfo.value.skill_dir || "未检测到");
  const mcpReadmePath = computed(() => appInfo.value.mcp_readme_path || "未检测到");
  const mcpExecutablePath = computed(() => appInfo.value.mcp_executable_path || "");
  const bundledNodePath = computed(() => appInfo.value.bundled_node_path || "");
  const runtimeModeLabel = computed(() =>
    appInfo.value.runtime_mode === "packaged" ? "安装包模式" : "开发模式"
  );
  const preferredMcpModeLabel = computed(() =>
    appInfo.value.preferred_mcp_launch_mode === "exe" ? "stdio(EXE)" : "Node(stdio/HTTP)"
  );
  const mcpLaunchHint = computed(() => {
    if (appInfo.value.preferred_mcp_launch_mode === "exe" && mcpExecutablePath.value) {
      return "当前已检测到独立 MCP 可执行文件，推荐直接用 stdio(EXE) 接入客户端；这样不依赖源码路径，也更适合打包分发。";
    }
    if (appInfo.value.bundled_node_exists && bundledNodePath.value) {
      return "当前安装包已内置 Node 运行时，可直接用内置 node.exe 启动随包分发的 MCP Server，无需用户另装 Node 环境。";
    }
    return "当前检测到的是 Node 版 MCP Server，适合开发调试。后续如果提供独立 MCP EXE，这里会自动切换为 EXE 启动指引。";
  });
  const mcpAvailabilityHint = computed(() => {
    if (appInfo.value.mcp_executable_exists) {
      return "";
    }
    if (!appInfo.value.mcp_server_entry_exists) {
      return "当前环境未检测到 MCP 入口文件，HTTP 模式和 Node 版 stdio 模式可能不可用。";
    }
    return "";
  });

  const mcpStdioCommand = computed(() => {
    if (appInfo.value.mcp_executable_exists && mcpExecutablePath.value) {
      return `& '${escapeForPowerShell(mcpExecutablePath.value)}'`;
    }
    if (appInfo.value.mcp_server_entry_exists && bundledNodePath.value) {
      return `& '${escapeForPowerShell(bundledNodePath.value)}' '${escapeForPowerShell(appInfo.value.mcp_server_entry)}'`;
    }
    if (appInfo.value.mcp_server_dir) {
      return `Set-Location '${escapeForPowerShell(appInfo.value.mcp_server_dir)}'
npm start`;
    }
    return "当前环境未检测到可用的 MCP 启动路径";
  });

  const mcpHttpCommand = computed(() => {
    if (!appInfo.value.mcp_server_entry_exists || !appInfo.value.mcp_server_dir) {
      return "当前环境未检测到 Node 版 MCP Server，HTTP 模式不可用";
    }
    if (bundledNodePath.value) {
      return `Set-Location '${escapeForPowerShell(appInfo.value.mcp_server_dir)}'
& '${escapeForPowerShell(bundledNodePath.value)}' server-http.js`;
    }
    return `Set-Location '${escapeForPowerShell(appInfo.value.mcp_server_dir)}'
npm run start:http`;
  });

  const mcpClientConfig = computed(() => {
    if (appInfo.value.mcp_executable_exists && mcpExecutablePath.value) {
      return `{
  "mcpServers": {
    "douyin-publisher": {
      "command": "${escapeForJson(mcpExecutablePath.value)}",
      "args": [],
      "env": {
        "DOUYIN_BACKEND_URL": "${backendUrl.value}",
        "DOUYIN_CDP_LIST_URL": "http://127.0.0.1:9333/json/list"
      }
    }
  }
}`;
    }

    return `{
  "mcpServers": {
    "douyin-publisher": {
      "command": "${escapeForJson(bundledNodePath.value || "node")}",
      "args": [
        "${escapeForJson(appInfo.value.mcp_server_entry || "<your-mcp-server-entry>")}"
      ],
      "env": {
        "DOUYIN_BACKEND_URL": "${backendUrl.value}",
        "DOUYIN_CDP_LIST_URL": "http://127.0.0.1:9333/json/list"
      }
    }
  }
}`;
  });

  async function loadAppInfo() {
    loading.value = true;
    loadError.value = "";
    try {
      appInfo.value = {
        ...defaultAppInfo,
        ...(await tauriCommands.getAppInfo()),
      };
    } catch (error) {
      console.error("加载应用运行时路径失败:", error);
      appInfo.value = { ...defaultAppInfo };
      loadError.value = "暂时无法检查扩展内容，请稍后重试";
    } finally {
      loading.value = false;
    }
  }

  return {
    appInfo,
    loading,
    loadError,
    backendUrl,
    mcpServerPath,
    mcpHttpEndpoint,
    skillPath,
    mcpReadmePath,
    mcpExecutablePath,
    runtimeModeLabel,
    preferredMcpModeLabel,
    mcpLaunchHint,
    mcpAvailabilityHint,
    mcpStdioCommand,
    mcpHttpCommand,
    mcpClientConfig,
    loadAppInfo,
  };
}
