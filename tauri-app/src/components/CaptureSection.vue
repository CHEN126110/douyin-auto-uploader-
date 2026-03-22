<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import type { CaptureHistoryTask, CaptureStatus } from "@/types";

const emit = defineEmits<{
  (e: "imported"): void;
}>();

const productStore = useProductStore();
const isDragOver = ref(false);

const url = ref("");
const isCapturing = ref(false);
const statusText = ref("准备就绪");
const statusStep = ref("");
const progress = ref(0);
const taskId = ref<string | null>(null);
const hasFailed = ref(false);
const canRetry = ref(false);
const taskOrigin = ref<"local" | "external" | null>(null);

let pollingInterval: number | null = null;
let discoveryInterval: number | null = null;
let pollingRetryCount = 0;
let lastExternalTaskNoticeId: string | null = null;

const MAX_POLLING_RETRIES = 5;
const POLLING_INTERVAL_MS = 2000;
const EXTERNAL_TASK_DISCOVERY_MS = 5000;

const statusType = computed(() => {
  if (hasFailed.value) return "error";
  if (progress.value >= 100) return "success";
  if (isCapturing.value) return "processing";
  return "idle";
});

function validateUrl(inputUrl: string): { valid: boolean; message: string } {
  if (!inputUrl.trim()) {
    return { valid: false, message: "请输入商品链接" };
  }

  const supportedDomains = [
    "taobao.com",
    "tmall.com",
    "detail.tmall.com",
    "item.taobao.com",
    "1688.com",
    "detail.1688.com",
    "www.1688.com",
    "offer.1688.com",
  ];

  if (!supportedDomains.some((domain) => inputUrl.includes(domain))) {
    return { valid: false, message: "仅支持淘宝/天猫/1688 商品链接" };
  }

  return { valid: true, message: "" };
}

function applyTaskSnapshot(task: CaptureHistoryTask) {
  taskId.value = task.task_id;
  isCapturing.value = true;
  hasFailed.value = false;
  canRetry.value = false;
  statusText.value = task.message || "正在采集中...";
  statusStep.value =
    task.status === "pending"
      ? "等待开始"
      : task.status === "running"
        ? "采集中"
        : task.status === "completed"
          ? "完成"
          : "失败";
  progress.value = task.progress || 0;
}

function stopPolling() {
  if (pollingInterval !== null) {
    window.clearInterval(pollingInterval);
    pollingInterval = null;
  }
}

function stopDiscovery() {
  if (discoveryInterval !== null) {
    window.clearInterval(discoveryInterval);
    discoveryInterval = null;
  }
}

function resetState() {
  isCapturing.value = false;
  hasFailed.value = false;
  canRetry.value = false;
  statusText.value = "准备就绪";
  statusStep.value = "";
  progress.value = 0;
  taskId.value = null;
  taskOrigin.value = null;
  pollingRetryCount = 0;
}

async function handleCompleted(_response: CaptureStatus) {
  stopPolling();
  statusText.value = "采集完成，正在导入数据...";
  statusStep.value = "导入数据";
  progress.value = 95;

  try {
    const importResponse = await api.importCaptureResult(taskId.value!);
    if (!importResponse.success) {
      throw new Error(importResponse.message || "导入失败");
    }

    const data = importResponse.data as { sku_count?: number } | undefined;
    statusText.value = `导入成功，${data?.sku_count || 0} 个SKU`;
    statusStep.value = "完成";
    progress.value = 100;
    ElMessage.success({
      message: `采集成功，已导入 ${data?.sku_count || 0} 个SKU`,
      duration: 3000,
    });
    emit("imported");

    window.setTimeout(() => {
      resetState();
      url.value = "";
    }, 3000);
  } catch (error: any) {
    const errorMsg = error?.message || "导入数据失败";
    handleFailed(errorMsg, true);
  }
}

function handleExternalCompleted(response: CaptureStatus) {
  stopPolling();
  statusText.value = response.message || "外部采集任务已完成";
  statusStep.value = "完成";
  progress.value = response.progress || 100;

  ElMessage.success({
    message: "检测到外部采集任务完成，已同步刷新产品列表",
    duration: 2500,
  });
  emit("imported");

  window.setTimeout(() => {
    resetState();
  }, 3000);
}

function handleFailed(message: string, allowRetry = taskOrigin.value === "local") {
  stopPolling();
  isCapturing.value = false;
  hasFailed.value = true;
  canRetry.value = allowRetry;
  statusText.value = message;
  statusStep.value = "失败";
  ElMessage.error({
    message,
    duration: 5000,
  });
}

function startPolling() {
  if (pollingInterval !== null) {
    window.clearInterval(pollingInterval);
  }

  pollingInterval = window.setInterval(async () => {
    if (!taskId.value) {
      stopPolling();
      return;
    }

    try {
      const response = await api.getCaptureStatus(taskId.value);
      pollingRetryCount = 0;

      if (!response.success) {
        return;
      }

      statusText.value = response.message || "处理中...";
      statusStep.value = response.current_step || "";
      progress.value = response.progress || 0;

      if (response.status === "completed") {
        if (taskOrigin.value === "external") {
          handleExternalCompleted(response);
        } else {
          await handleCompleted(response);
        }
      } else if (response.status === "failed") {
        handleFailed(response.message || "采集失败");
      }
    } catch (error) {
      console.error("查询采集状态失败:", error);
      pollingRetryCount += 1;

      if (pollingRetryCount >= MAX_POLLING_RETRIES) {
        handleFailed("连接服务超时，请检查后端服务是否正常运行");
      }
    }
  }, POLLING_INTERVAL_MS);
}

async function syncExternalCaptureTask(options: { silent?: boolean } = {}) {
  if (productStore.backendStatus !== "online") {
    return false;
  }

  if (taskOrigin.value === "local" && isCapturing.value) {
    return false;
  }

  try {
    const response = await api.getCaptureHistory();
    const tasks = response.data?.tasks || [];
    const activeTask = [...tasks]
      .filter((task) => task.status === "pending" || task.status === "running")
      .sort((left, right) =>
        String(right.created_at || "").localeCompare(String(left.created_at || ""))
      )[0];

    if (!activeTask) {
      return false;
    }

    const isNewExternalTask =
      taskOrigin.value !== "external" || taskId.value !== activeTask.task_id;

    taskOrigin.value = "external";
    applyTaskSnapshot(activeTask);

    if (isNewExternalTask && lastExternalTaskNoticeId !== activeTask.task_id) {
      lastExternalTaskNoticeId = activeTask.task_id;
      if (!options.silent) {
        ElMessage.info("检测到外部采集任务，已同步前端状态");
      }
    }

    if (pollingInterval === null) {
      startPolling();
    }
    return true;
  } catch (error) {
    if (!options.silent) {
      console.warn("同步外部采集任务失败:", error);
    }
    return false;
  }
}

function startDiscovery() {
  stopDiscovery();
  discoveryInterval = window.setInterval(() => {
    if (document.visibilityState === "hidden") {
      return;
    }
    void syncExternalCaptureTask({ silent: true });
  }, EXTERNAL_TASK_DISCOVERY_MS);
}

async function startCapture() {
  const validation = validateUrl(url.value);
  if (!validation.valid) {
    ElMessage.warning(validation.message);
    return;
  }

  hasFailed.value = false;
  canRetry.value = false;
  pollingRetryCount = 0;
  taskOrigin.value = "local";

  isCapturing.value = true;
  statusText.value = "正在连接服务...";
  statusStep.value = "初始化";
  progress.value = 5;

  try {
    const response = await api.startCapture(url.value, {
      download_images: true,
      extract_sku: true,
      extract_params: true,
      save_path: "uploads/products",
    });

    if (!response.success || !response.data?.task_id) {
      throw new Error("服务端返回异常");
    }

    taskId.value = response.data.task_id;
    statusText.value = "任务已创建，正在启动浏览器...";
    statusStep.value = "启动浏览器";
    progress.value = 10;
    ElMessage.success("采集任务已启动");
    startPolling();
  } catch (error: any) {
    console.error("启动采集失败:", error);
    const errorMsg = error?.response?.data?.message || error?.message || "未知错误";
    handleFailed(`启动失败：${errorMsg}`, true);
  }
}

async function cancelCapture() {
  if (!taskId.value) {
    resetState();
    return;
  }

  try {
    await ElMessageBox.confirm("确定要取消当前采集任务吗？", "取消采集", {
      type: "warning",
      confirmButtonText: "确定取消",
      cancelButtonText: "继续采集",
    });

    try {
      await api.cancelCapture(taskId.value);
    } catch {
      // Ignore cancellation failures and reset local state anyway.
    }

    stopPolling();
    ElMessage.info("采集任务已取消");
    resetState();
  } catch {
    // User chose to continue capturing.
  }
}

function retryCapture() {
  hasFailed.value = false;
  canRetry.value = false;
  void startCapture();
}

function handleDrop(_event: DragEvent) {
  isDragOver.value = false;
}

function handleZoneDrag(event: DragEvent) {
  isDragOver.value = true;
  if (event.dataTransfer) {
    event.dataTransfer.dropEffect = "copy";
  }
}

void handleDrop;
void handleZoneDrag;

async function openFolderPicker() {
  await productStore.importFromPicker();
}

onMounted(() => {
  void syncExternalCaptureTask({ silent: true });
  startDiscovery();
});

onUnmounted(() => {
  stopPolling();
  stopDiscovery();
});
</script>

<template>
  <div class="capture-container">
    <div class="drop-zone" @click="openFolderPicker">
      <div class="drop-text">请将待处理文件夹拖入此处</div>
    </div>

    <div class="capture-section">
      <div class="capture-header">
        <span class="capture-icon">采集</span>
        <h3>链接采集</h3>
        <span class="capture-hint">支持淘宝/天猫/1688 商品链接</span>
      </div>

      <div class="capture-input-group">
        <el-input
          v-model="url"
          placeholder="粘贴淘宝/天猫商品链接..."
          :disabled="isCapturing"
          class="capture-input"
          clearable
          @keyup.enter="startCapture"
        >
          <template #prefix>
            <span class="input-prefix">链接</span>
          </template>
        </el-input>

        <template v-if="!isCapturing && !hasFailed">
          <el-button type="primary" class="capture-btn" @click="startCapture">
            <span class="btn-icon">开始</span>
            <span>开始采集</span>
          </el-button>
        </template>

        <template v-else-if="isCapturing && !hasFailed">
          <el-button type="warning" class="capture-btn cancel-btn" @click="cancelCapture">
            <span class="btn-icon">取消</span>
            <span>取消</span>
          </el-button>
        </template>

        <template v-else-if="hasFailed && canRetry">
          <el-button type="primary" class="capture-btn" @click="retryCapture">
            <span class="btn-icon">重试</span>
            <span>重试</span>
          </el-button>
          <el-button type="info" class="capture-btn reset-btn" @click="resetState">
            <span>重置</span>
          </el-button>
        </template>
      </div>

      <div v-if="isCapturing || hasFailed" class="capture-status" :class="statusType">
        <div class="status-content">
          <div v-if="!hasFailed" class="status-loader"></div>
          <span v-else class="status-icon error">错误</span>
          <div class="status-info">
            <span class="status-text">{{ statusText }}</span>
            <span v-if="statusStep && !hasFailed" class="status-step">{{ statusStep }}</span>
          </div>
        </div>
        <div v-if="!hasFailed" class="status-progress">
          <div class="progress-bar" :style="{ width: progress + '%' }"></div>
          <span class="progress-text">{{ progress }}%</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.capture-container {
  display: flex;
  flex-direction: column;
}

.drop-zone {
  margin: 16px;
  padding: 36px 16px;
  border: 2px dashed #5c7cfa;
  border-radius: var(--radius-md);
  background: white;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;

  &:hover {
    background: rgba(92, 124, 250, 0.05);
    border-color: #4263eb;
  }

  &.drag-over {
    background: rgba(92, 124, 250, 0.1);
    border-color: #4263eb;
    border-style: solid;

    .drop-text {
      color: #4263eb;
    }
  }

  .drop-text {
    font-size: 14px;
    font-weight: bold;
    color: #5c7cfa;
    letter-spacing: 1px;
  }
}

.capture-section {
  padding: 16px;
  border-bottom: 2px solid rgba(92, 124, 250, 0.1);
  background: linear-gradient(
    135deg,
    rgba(92, 124, 250, 0.03) 0%,
    rgba(116, 143, 252, 0.03) 100%
  );
}

.capture-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;

  .capture-icon {
    font-size: 15px;
    font-weight: 700;
    color: var(--primary-color);
  }

  h3 {
    margin: 0;
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--text-primary);
  }

  .capture-hint {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-secondary);
  }
}

.capture-input-group {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.capture-input {
  flex: 1;
  min-width: 200px;

  .input-prefix {
    font-size: 14px;
  }
}

.capture-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  white-space: nowrap;
  height: 40px !important;
  padding: 0 16px !important;
  font-size: var(--font-size-sm) !important;
  font-weight: 600;

  &.cancel-btn {
    background: #f39c12;
    border-color: #f39c12;

    &:hover {
      background: #e67e22;
      border-color: #e67e22;
    }
  }

  &.reset-btn {
    padding: 0 12px !important;
  }
}

.btn-icon {
  font-size: 12px;
}

.capture-status {
  margin-top: 12px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.9);
  border-radius: var(--radius-sm);
  border: 1px solid rgba(92, 124, 250, 0.2);

  &.error {
    background: rgba(231, 76, 60, 0.05);
    border-color: rgba(231, 76, 60, 0.3);
  }

  &.success {
    background: rgba(39, 174, 96, 0.05);
    border-color: rgba(39, 174, 96, 0.3);
  }
}

.status-content {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.status-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.status-loader {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(92, 124, 250, 0.2);
  border-top-color: var(--primary-color);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  flex-shrink: 0;
}

.status-icon {
  font-size: 13px;
  font-weight: 600;
  flex-shrink: 0;

  &.error {
    color: #e74c3c;
  }
}

.status-text {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  font-weight: 500;
}

.status-step {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.status-progress {
  height: 6px;
  background: rgba(92, 124, 250, 0.1);
  border-radius: 3px;
  overflow: hidden;
  position: relative;
}

.progress-bar {
  height: 100%;
  background: var(--primary-gradient);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-text {
  position: absolute;
  right: 0;
  top: -18px;
  font-size: 11px;
  color: var(--text-secondary);
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
