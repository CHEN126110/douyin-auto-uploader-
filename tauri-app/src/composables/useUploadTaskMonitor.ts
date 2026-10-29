import { computed, h, onMounted, onUnmounted, ref } from "vue";
import { ElButton, ElLoading, ElMessage, ElMessageBox } from "element-plus";
import { api, apiErrorMessage } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import { isVerifiedTaobaoFillResult, isVerifiedTaobaoPublishResult } from "@/utils/taobaoFormVerification";
import type { TargetPublishPlatform, UploadProgressStep } from "@/types";

const UPLOAD_POLL_INTERVAL_MS = 800;
// 发现外部任务（别处启动的上传）的轮询间隔，由 useExternalUploadDiscovery 使用
const UPLOAD_DISCOVERY_INTERVAL_MS = 15000;
const UPLOAD_TIMEOUT_MS = 15 * 60 * 1000;
// 连续多少次拿不到上传状态才判定为「无法获取状态」并停止轮询
const UPLOAD_POLL_MAX_FAILURES = 5;

/**
 * 上传 / 发布任务的监控：轮询后台任务进度、全屏进度遮罩、完成后的结果提示、
 * 以及「接上别处已经在跑的任务」。抖音、淘宝、小红书三个平台共用同一套监控。
 *
 * 发起发布本身不在这里（见 usePublishFlow）；这里只负责「任务一旦存在，如何如实地跟进到结束」，
 * 并给出整个主页共用的忙碌状态 `uploadBusy`——发布进行中，界面上其它会改动数据的操作都要让路。
 */
export function useUploadTaskMonitor() {
  const productStore = useProductStore();

  const activeUploadTaskId = ref<string | null>(null);
  const activeUploadTaskOrigin = ref<"local" | "external" | null>(null);
  const activeUploadTaskPlatform = ref<TargetPublishPlatform | null>(null);
  const activeUploadContext = ref<{ recordId: number; accountProfile: string } | null>(null);
  const isUploadMonitoring = computed(() => Boolean(activeUploadTaskId.value));
  const isUploadStarting = ref(false);
  const taobaoUnknownStart = ref<{ recordId: number; accountProfile: string; requestedAt: number } | null>(null);
  const uploadBusy = computed(() =>
    Boolean(taobaoUnknownStart.value) ||
    isUploadStarting.value || isUploadMonitoring.value
  );
  const uploadTaskCancelling = ref(false);

  let uploadMonitorTimer: number | null = null;
  let uploadMonitorStartedAt = 0;
  // 连续获取上传状态失败的次数（仅统计传输层异常，不代表上传本身失败）
  let uploadPollFailureCount = 0;
  // 在途轮询属于具体任务：旧任务等待用户确认终态弹窗时，新任务不能被旧锁堵住。
  let uploadPollInFlightTaskId: string | null = null;
  let uploadDiscoveryInFlight = false;
  let uploadLoading: ReturnType<typeof ElLoading.service> | null = null;
  let lastExternalUploadNoticeId: string | null = null;

  const uploadMonitoringPaused = ref(false);
  const uploadLoadingMessage = ref("");
  const uploadLoadingText = computed(() => h("div", { class: "upload-loading-content" }, [
    h("div", { role: "status", "aria-live": "polite" }, uploadLoadingMessage.value),
    activeUploadTaskId.value ? h(ElButton, {
      type: "warning", size: "small", loading: uploadTaskCancelling.value, onClick: cancelUploadTask,
    }, () => "取消上传") : null,
  ]));
  const uploadStatusText = ref("");
  const uploadProgress = ref(0);
  const uploadSteps = ref<UploadProgressStep[]>([]);

  function ensureUploadLoading(text: string) {
    uploadLoadingMessage.value = text;
    if (!uploadLoading) {
      uploadLoading = ElLoading.service({
        text: uploadLoadingText,
        background: "rgba(0, 0, 0, 0.35)",
        customClass: "product-upload-loading",
      });
    }
  }

  function closeUploadLoading() {
    if (uploadLoading) {
      uploadLoading.close();
      uploadLoading = null;
    }
  }

  function stopUploadMonitoring(closeLoading = true) {
    if (uploadMonitorTimer !== null) {
      window.clearInterval(uploadMonitorTimer);
      uploadMonitorTimer = null;
    }

    activeUploadTaskId.value = null;
    activeUploadTaskOrigin.value = null;
    activeUploadTaskPlatform.value = null;
    activeUploadContext.value = null;
    uploadMonitorStartedAt = 0;
    uploadMonitoringPaused.value = false;
    uploadPollFailureCount = 0;
    uploadSteps.value = [];

    if (closeLoading) {
      closeUploadLoading();
    }
  }

  async function refreshAfterUpload() {
    await productStore.fetchProducts({ silent: true });
    if (productStore.currentProductId) {
      await productStore.refreshCurrentProductSilently();
    }
  }

  async function handleUploadTerminal(data: any) {
    const origin = activeUploadTaskOrigin.value;
    const platform = activeUploadTaskPlatform.value;
    stopUploadMonitoring();
    await refreshAfterUpload();

    if (platform === "taobao" && ["succeeded", "success"].includes(data?.status)) {
      const realPublish = data?.stop_before_submit === false;
      if (realPublish) {
        if (isVerifiedTaobaoPublishResult(data)) {
          await ElMessageBox.alert(
            "流水线已完成并执行了提交。是否已上架请在卖家中心核对",
            origin === "external" ? "外部上传完成" : "发布完成",
            { type: "success" }
          );
        } else {
          await ElMessageBox.alert(
            "任务已结束，但提交结果未能确认。请到卖家中心核对商品状态",
            "发布结果", { type: "warning" }
          );
        }
        return;
      }
      if (isVerifiedTaobaoFillResult(data)) {
        await ElMessageBox.alert(
          "本次填写与回读已完成，已停在提交前",
          origin === "external" ? "外部上传完成" : "上传完成",
          { type: "success" }
        );
      } else {
        await ElMessageBox.alert(
          "任务已结束，但未确认完整填写并停在提交前。整页必填尚未确认时，不能认定填写完成，请核对任务结果",
          "上传结果", { type: "warning" }
        );
      }
      return;
    }

    if (data?.status === "success") {
      const title = origin === "external" ? "外部上传完成" : "上传完成";
      await ElMessageBox.alert(data?.message || "上传完成", title, { type: "success" });
      return;
    }

    if (data?.status === "failed") {
      await ElMessageBox.alert(
        data?.error || "上传失败（未知原因）",
        origin === "external" ? "外部上传失败" : "上传失败",
        { type: "error" }
      );
      return;
    }

    if (data?.status === "cancelled") {
      ElMessage.warning(origin === "external" ? "外部上传已取消" : "上传已取消");
    }
  }

  async function pollUploadTask() {
    const taskId = activeUploadTaskId.value;
    if (!taskId || uploadPollInFlightTaskId === taskId) return;
    uploadPollInFlightTaskId = taskId;
    try {
      await pollUploadTaskOnce();
    } finally {
      // 旧任务结束时不得误清新任务的在途标记。
      if (uploadPollInFlightTaskId === taskId) uploadPollInFlightTaskId = null;
    }
  }

  function pauseUploadMonitoring(message: string) {
    if (uploadMonitorTimer !== null) {
      window.clearInterval(uploadMonitorTimer);
      uploadMonitorTimer = null;
    }
    uploadStatusText.value = message;
    uploadMonitoringPaused.value = true;
    closeUploadLoading();
  }

  async function retryUploadProgress() {
    if (taobaoUnknownStart.value && !activeUploadTaskId.value) {
      if (!(await syncExternalUploadTask({ silent: true }))) {
        ElMessage.warning("尚未读取到这次淘宝填写的任务结果；可能仍在启动，请稍后重新读取，不会重复发起");
      }
      return;
    }
    if (!activeUploadTaskId.value) return;
    uploadMonitoringPaused.value = false;
    ensureUploadLoading("正在读取上传进度…");
    uploadPollFailureCount = 0;
    uploadMonitorStartedAt = Date.now();
    if (uploadMonitorTimer === null) {
      uploadMonitorTimer = window.setInterval(() => void pollUploadTask(), UPLOAD_POLL_INTERVAL_MS);
    }
    void pollUploadTask();
  }

  async function cancelUploadTask() {
    const taskId = activeUploadTaskId.value;
    const platform = activeUploadTaskPlatform.value;
    if (!taskId || !platform || uploadTaskCancelling.value) return;
    uploadTaskCancelling.value = true;
    try {
      const response = platform === "taobao"
        ? await api.cancelTaobaoPublish(taskId)
        : platform === "xiaohongshu"
          ? await api.cancelXhsFill(taskId)
          : await api.cancelUpload(taskId);
      if (!response.success) throw new Error(response.message || response.msg || "后端未接受取消请求");
      ElMessage.info("已请求取消，将在当前阶段结束后停止");
      void retryUploadProgress();
    } catch (error) {
      const reason = apiErrorMessage(error);
      ElMessage.error(`取消上传失败：${reason}`);
    } finally {
      uploadTaskCancelling.value = false;
    }
  }

  async function pollUploadTaskOnce() {
    if (!activeUploadTaskId.value) {
      stopUploadMonitoring();
      return;
    }

    const taskId = activeUploadTaskId.value;
    const platform = activeUploadTaskPlatform.value;
    let statusResp: any;
    try {
      statusResp = platform === "taobao"
        ? await api.getTaobaoPublishStatus(taskId)
        : platform === "xiaohongshu"
          ? await api.getXhsFillStatus(taskId)
          : await productStore.getUploadStatus(taskId);
      if (activeUploadTaskId.value !== taskId || activeUploadTaskPlatform.value !== platform) return;
      if (!statusResp.success || !statusResp.data || statusResp.data.task_id !== taskId) {
        throw new Error(statusResp.message || statusResp.msg || "后端未返回当前任务状态");
      }
      if (platform === "taobao" && (statusResp.data.platform !== "taobao" ||
          (activeUploadContext.value && (statusResp.data.record_id !== activeUploadContext.value.recordId ||
            statusResp.data.account_profile !== activeUploadContext.value.accountProfile)))) {
        throw new Error("淘宝任务返回的账户或商品与启动时不一致，未应用进度");
      }
    } catch (error) {
      if (activeUploadTaskId.value !== taskId || activeUploadTaskPlatform.value !== platform) return;
      // 传输层异常（超时 / 连接被拒）只说明「拿不到状态」，后台上传线程仍在继续，
      // 不能当成上传失败。连续失败达到阈值才停止轮询并如实提示。
      console.error("获取上传状态失败:", error);
      uploadPollFailureCount += 1;
      if (uploadPollFailureCount < UPLOAD_POLL_MAX_FAILURES) {
        return;
      }
      pauseUploadMonitoring("无法获取上传进度，任务可能仍在运行；请重新读取进度或请求取消，勿重复启动");
      return;
    }

    uploadPollFailureCount = 0;

    const data = (statusResp as any)?.data;
    const progress = data?.progress ?? 0;
    const msg = data?.message || "上传进行中...";
    const status = data?.status;

    uploadProgress.value = progress;
    uploadStatusText.value = msg;
    if (data?.steps && Array.isArray(data.steps)) {
      uploadSteps.value = data.steps;
    }

    ensureUploadLoading(`上传中：${progress}% - ${msg}`);

    if (uploadMonitorStartedAt > 0 && Date.now() - uploadMonitorStartedAt > UPLOAD_TIMEOUT_MS) {
      if (status === "pending" || status === "running") {
        pauseUploadMonitoring("上传超过 15 分钟，后端尚未结束；可重新读取进度或请求取消");
        return;
      }
    }

    if (status === "success" || (platform === "taobao" && status === "succeeded") || status === "failed" || status === "cancelled") {
      await handleUploadTerminal(data);
    }
  }

  function startUploadMonitoring(
    taskId: string,
    origin: "local" | "external",
    createdAt?: string | null,
    platform: TargetPublishPlatform = "douyin",
    context?: { recordId: number; accountProfile: string }
  ) {
    activeUploadTaskId.value = taskId;
    activeUploadTaskOrigin.value = origin;
    activeUploadTaskPlatform.value = platform;
    activeUploadContext.value = context ? { ...context } : null;
    uploadMonitoringPaused.value = false;
    ensureUploadLoading("正在读取上传进度…");
    uploadMonitorStartedAt = createdAt ? Date.parse(createdAt) || Date.now() : Date.now();
    uploadPollFailureCount = 0;

    if (uploadMonitorTimer !== null) {
      window.clearInterval(uploadMonitorTimer);
    }

    uploadMonitorTimer = window.setInterval(() => {
      void pollUploadTask();
    }, UPLOAD_POLL_INTERVAL_MS);

    void pollUploadTask();
  }

  async function syncExternalUploadTask(options: { silent?: boolean } = {}) {
    if (activeUploadTaskId.value || uploadDiscoveryInFlight) return false;
    uploadDiscoveryInFlight = true;
    try {
      const [douyinResult, taobaoResult] = await Promise.allSettled([
        api.getUploadTasks({ silentError: !!options.silent }),
        api.listTaobaoPublishTasks(),
      ]);
      if (activeUploadTaskId.value) return false;
      const candidates: Array<{ platform: TargetPublishPlatform; task: any }> = [];
      const unknownStart = taobaoUnknownStart.value;
      if (douyinResult.status === "fulfilled" && douyinResult.value.success) {
        const data = douyinResult.value.data;
        const tasks = data?.tasks || [];
        const currentTaskId = data?.browser_status?.current_task;
        const active = tasks.find((task) => task.task_id === currentTaskId && (task.status === "pending" || task.status === "running")) ||
          [...tasks].filter((task) => task.status === "pending" || task.status === "running")
            .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))[0];
        if (active && !unknownStart) candidates.push({ platform: "douyin", task: active });
      }
      if (taobaoResult.status === "fulfilled" && taobaoResult.value.success) {
        const active = (taobaoResult.value.data?.tasks || [])
          .filter((task) => task.platform === "taobao" && (unknownStart
            ? task.record_id === unknownStart.recordId && task.account_profile === unknownStart.accountProfile &&
              Date.parse(task.created_at) >= unknownStart.requestedAt
            : task.status === "pending" || task.status === "running"))
          .sort((left, right) => String(right.created_at || "").localeCompare(String(left.created_at || "")))[0];
        if (active) candidates.push({ platform: "taobao", task: active });
      }
      const candidate = candidates.sort((left, right) =>
        String(right.task.created_at || "").localeCompare(String(left.task.created_at || "")))[0];
      if (!candidate) {
        if (!options.silent) {
          for (const result of [douyinResult, taobaoResult]) {
            if (result.status === "rejected") console.warn("同步外部任务失败:", result.reason);
          }
        }
        return false;
      }
      const task = candidate.task;
      if (unknownStart && candidate.platform === "taobao") taobaoUnknownStart.value = null;
      ensureUploadLoading(`检测到外部上传：${task.progress}% - ${task.message}`);
      startUploadMonitoring(task.task_id, "external", task.started_at || task.created_at || null, candidate.platform,
        candidate.platform === "taobao" && typeof task.record_id === "number" && typeof task.account_profile === "string"
          ? { recordId: task.record_id, accountProfile: task.account_profile } : undefined);
      if (!options.silent && lastExternalUploadNoticeId !== task.task_id) {
        lastExternalUploadNoticeId = task.task_id;
        ElMessage.info("检测到正在进行的任务，已自动接上进度");
      }
      return true;
    } finally {
      uploadDiscoveryInFlight = false;
    }
  }

  function triggerExternalUploadSync() {
    if (document.visibilityState === "hidden") {
      return;
    }

    void syncExternalUploadTask({ silent: true });
  }

  onUnmounted(() => {
    stopUploadMonitoring();
  });

  return {
    // 状态（界面用）
    activeUploadTaskId,
    isUploadMonitoring,
    isUploadStarting,
    taobaoUnknownStart,
    uploadBusy,
    uploadTaskCancelling,
    uploadMonitoringPaused,
    uploadStatusText,
    uploadProgress,
    uploadSteps,
    // 操作
    ensureUploadLoading,
    closeUploadLoading,
    startUploadMonitoring,
    stopUploadMonitoring,
    syncExternalUploadTask,
    triggerExternalUploadSync,
    retryUploadProgress,
    cancelUploadTask,
  };
}

export type UploadTaskMonitor = ReturnType<typeof useUploadTaskMonitor>;

/**
 * 常驻的「外部任务发现」：主页挂载时、窗口重新获得焦点 / 变为可见时、以及每隔一段时间，
 * 去问后台有没有别处（MCP、旧窗口）已经启动的任务，有就接上进度。
 */
export function useExternalUploadDiscovery(monitor: Pick<UploadTaskMonitor, "syncExternalUploadTask" | "triggerExternalUploadSync">) {
  let uploadDiscoveryTimer: number | null = null;

  onMounted(() => {
    void monitor.syncExternalUploadTask({ silent: true });
    window.addEventListener("focus", monitor.triggerExternalUploadSync);
    document.addEventListener("visibilitychange", monitor.triggerExternalUploadSync);
    uploadDiscoveryTimer = window.setInterval(() => {
      monitor.triggerExternalUploadSync();
    }, UPLOAD_DISCOVERY_INTERVAL_MS);
  });

  onUnmounted(() => {
    if (uploadDiscoveryTimer !== null) {
      window.clearInterval(uploadDiscoveryTimer);
      uploadDiscoveryTimer = null;
    }
    window.removeEventListener("focus", monitor.triggerExternalUploadSync);
    document.removeEventListener("visibilitychange", monitor.triggerExternalUploadSync);
  });
}
