/**
 * 应用内自动更新（Tauri 2 updater）
 *
 * 流程：check() 读取 GitHub Release 上的 latest.json → 比对版本 → 有新版则提示 →
 * 下载前先优雅停掉 python-backend（关键：否则覆盖安装时 exe 被占用会失败）→
 * downloadAndInstall() 下载 + 验签 + 安装 → relaunch() 重启。
 *
 * 本应用是「整包更新」：安装包内置 python-backend.exe + node 运行时，体积较大，
 * 所以进度条是刚需，且更新前必须停后端。
 */
import { check } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { ElMessage, ElMessageBox, ElLoading } from "element-plus";

const BACKEND_URL = "http://127.0.0.1:5001";

/** 更新前优雅停掉 python-backend，避免覆盖安装时 exe 文件被占用导致失败 */
async function gracefullyStopBackend(): Promise<void> {
  try {
    await fetch(`${BACKEND_URL}/internal/terminate`, { method: "POST" });
  } catch {
    // 后端可能已经停了，或本就未启动，忽略
  }
}

function formatMB(bytes: number): string {
  return (bytes / 1024 / 1024).toFixed(1);
}

/**
 * 检查并执行更新。
 * @param opts.silent 静默模式（如开机自动检查）：没有新版本时不弹"已是最新"提示，
 *                    检查出错也不打扰用户。
 */
export async function checkForUpdate(opts?: { silent?: boolean }): Promise<void> {
  const silent = opts?.silent ?? false;

  let update;
  try {
    update = await check();
  } catch (e: any) {
    if (!silent) {
      ElMessage.error(`检查更新失败：${e?.message || e}`);
    }
    return;
  }

  if (!update) {
    if (!silent) {
      ElMessage.success("当前已是最新版本");
    }
    return;
  }

  // 发现新版本，弹确认（展示版本号 + 更新说明）
  try {
    await ElMessageBox.confirm(
      `发现新版本 ${update.version}\n\n更新说明：${update.body || "（无）"}\n\n` +
        `提示：更新需要下载完整安装包（含后端，体积较大），更新前请先确保没有正在进行的采集 / 发布任务。`,
      "发现新版本",
      {
        confirmButtonText: "立即更新",
        cancelButtonText: "稍后",
        type: "info",
      }
    );
  } catch {
    return; // 用户选择稍后
  }

  const loading = ElLoading.service({
    lock: true,
    text: "正在停止后端服务...",
    background: "rgba(0, 0, 0, 0.75)",
  });

  try {
    // 关键：先停后端，避免覆盖安装时 python-backend.exe 被占用
    await gracefullyStopBackend();

    let total = 0;
    let downloaded = 0;
    await update.downloadAndInstall((event) => {
      switch (event.event) {
        case "Started":
          total = event.data.contentLength || 0;
          loading.setText("开始下载更新...");
          break;
        case "Progress":
          downloaded += event.data.chunkLength;
          loading.setText(
            total
              ? `下载中 ${Math.round((downloaded / total) * 100)}%（${formatMB(downloaded)}/${formatMB(total)} MB）`
              : `下载中 ${formatMB(downloaded)} MB`
          );
          break;
        case "Finished":
          loading.setText("下载完成，正在安装...");
          break;
      }
    });
  } catch (e: any) {
    loading.close();
    ElMessage.error(`更新失败：${e?.message || e}`);
    return;
  }

  loading.close();

  // 安装完成，提示重启
  try {
    await ElMessageBox.confirm("更新已安装，需要重启应用才能生效。", "更新完成", {
      confirmButtonText: "立即重启",
      cancelButtonText: "稍后手动重启",
      type: "success",
    });
    await relaunch();
  } catch {
    // 用户选稍后手动重启
  }
}
