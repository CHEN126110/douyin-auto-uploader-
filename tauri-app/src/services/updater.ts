/**
 * 应用内自动更新（Tauri 2 updater）
 *
 * 流程：check() 读取 GitHub Release 上的 latest.json → 比对版本 → 有新版则提示 →
 * download() 下载 + 验签 → 停掉 python-backend（覆盖安装要释放 exe 占用）→
 * install() 安装 → relaunch() 重启。
 *
 * 为什么拆成 download + install 而不是用 downloadAndInstall：
 * 整包 110 MB 从 GitHub 下载，断流/超时/验签失败都是常态。若像原先那样先停后端再下载，
 * 一旦下载失败，用户就停在「应用开着但商品列表、采集、发布全都用不了」的状态，
 * 且没有任何恢复入口。拆开后下载阶段后端一直活着，只有临安装前才停；
 * 安装若失败还会把后端拉回来。
 */
import { check } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { invoke } from "@tauri-apps/api/core";
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
    text: "正在准备更新...",
    background: "rgba(0, 0, 0, 0.75)",
  });

  try {
    // 下载 + 验签：这一步后端保持运行，失败了应用还能照常用
    let total = 0;
    let downloaded = 0;
    await update.download((event) => {
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
          loading.setText("下载完成，准备安装...");
          break;
      }
    });

    // 只有覆盖安装才需要释放 python-backend.exe 的文件占用
    loading.setText("正在停止后端服务...");
    await gracefullyStopBackend();

    try {
      loading.setText("正在安装...");
      await update.install();
    } catch (installError) {
      // 安装失败必须把后端拉回来，否则用户停在「应用开着但什么都干不了」的状态
      try {
        await invoke("start_python_backend");
      } catch {
        // 拉不起来就只能靠用户重启应用，这里不再叠加二次报错
      }
      throw installError;
    }
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
