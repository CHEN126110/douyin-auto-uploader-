<script setup lang="ts">
/**
 * 白底图生成面板。
 *
 * 平台的「一键抠图 → 白底图」是显著性抠图，会把摆拍的鞋子、毯子一起抠进来；
 * 这里改成语义抠图，只留袜子，再转正、贴到 1:1 白底正中。
 *
 * 界面只呈现人看得懂的东西：成了几张、图长什么样、没成的那张为什么不成。
 * 模型名、文件路径、置信度分数这些留在后端报告里，不摆到界面上。
 */
import { computed, onUnmounted, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/services/api";
import type { WhiteBgItem, WhiteBgTask } from "@/types";

const props = defineProps<{
  /** 当前商品记录 id；没有就禁用按钮 */
  recordId: number | null;
  /** 商品名，只用于弹窗标题 */
  recordName?: string;
  /** 外层商品图片窗口是否打开；后台完成时不强行弹出结果窗口 */
  active?: boolean;
  disabled?: boolean;
}>();

const emit = defineEmits<{
  (e: "done", payload: { recordId: number; successCount: number; total: number }): void;
}>();

const running = ref(false);
const progress = ref(0);
const statusText = ref("");
const resultVisible = ref(false);
const items = ref<WhiteBgItem[]>([]);
const summary = ref("");
const taskRecordId = ref<number | null>(null);
const taskRecordName = ref("");
const hasResult = ref(false);
defineExpose({ running, taskRecordId });
let disposed = false;
onUnmounted(() => { disposed = true; });
watch(() => [props.active, props.recordId], () => { resultVisible.value = false; });
const canShowResult = computed(() => hasResult.value && taskRecordId.value === props.recordId);

const okItems = computed(() => items.value.filter((i) => i.white_ok));
const badItems = computed(() => items.value.filter((i) => !i.white_ok));

/** 把后端的拒绝码翻成一句人话 */
const REASON_TEXT: Record<string, string> = {
  worn_source: "这张是穿在脚上/腿上的图，袜子和腿连在一起，抠不出单独的袜子",
  no_sock_found: "画面里认不出单独的袜子（多是多色对照图或以包装为主体的图）",
  no_foreground: "整张图分不出主体，可能是纯色图或过曝",
  exception: "图片读取失败，文件可能已损坏",
};

function reasonOf(item: WhiteBgItem): string {
  return REASON_TEXT[item.code] || item.message || "未能生成";
}

function imageUrl(path: string): string {
  return api.whiteBgImageUrl(path);
}

function errorText(error: unknown) {
  const failure = error as { response?: { data?: { msg?: string; message?: string } }; message?: string };
  return failure?.response?.data?.msg || failure?.response?.data?.message || failure?.message || String(error);
}

function isCurrentProduct(recordId: number) {
  return !disposed && props.recordId === recordId && props.active !== false;
}

async function start() {
  if (running.value || props.disabled || props.active === false) return;
  if (!props.recordId) {
    ElMessage.warning("请先选择一个商品");
    return;
  }

  // 在任何 await 之前锁定本次商品和按钮，不能让异步状态检查改变处理对象。
  const recordId = props.recordId;
  const recordName = props.recordName || `商品 ${recordId}`;
  running.value = true;
  progress.value = 0;
  statusText.value = "正在检查处理环境";

  try {
    const status = await api.getWhiteBgStatus();
    if (!isCurrentProduct(recordId) || props.disabled) return;
    if (!status?.success || !status.data) {
      throw new Error(status?.msg || status?.message || "白底图处理环境读取失败");
    }
    if (!status.data.ready) {
      await ElMessageBox.alert(
        "白底图功能需要的本地模型尚未就绪，装好后即可使用。现有图片可以继续查看。",
        "模型未就绪", { confirmButtonText: "知道了" }
      );
      return;
    }
    taskRecordId.value = recordId;
    taskRecordName.value = recordName;
    items.value = [];
    summary.value = "";
    hasResult.value = false;
    resultVisible.value = false;
    statusText.value = "正在准备";
    const started = await api.startWhiteBg({ recordId });
    const taskId = started?.data?.task_id;
    if (!started?.success || !taskId) {
      if (!disposed) ElMessage.error(started?.msg || started?.message || "白底图任务启动失败");
      return;
    }
    const task = await poll(taskId, recordId);
    if (disposed) return;
    if (!task) {
      ElMessage.error("白底图处理仍未返回结果，请稍后查看图片目录，避免重复启动");
      return;
    }
    items.value = [...(task.result?.items || []), ...(task.result?.fallback_items || [])];
    summary.value = task.message || "";
    hasResult.value = true;
    resultVisible.value = isCurrentProduct(recordId);
    emit("done", {
      recordId,
      successCount: okItems.value.length,
      total: items.value.length,
    });
    if (task.status === "success") {
      ElMessage.success(task.message || "白底图已生成");
    } else {
      ElMessage.warning(task.message || "白底图未能生成");
    }
  } catch (error) {
    if (!disposed) ElMessage.error(`白底图生成失败：${errorText(error)}`);
  } finally {
    running.value = false;
    statusText.value = "";
  }
}

/** 轮询任务。7 张图约 80 秒，这里最多等 10 分钟 */
async function poll(taskId: string, recordId: number): Promise<WhiteBgTask | null> {
  for (let i = 0; i < 300 && !disposed; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 2000));
    if (disposed) return null;
    const response = await api.getWhiteBgTask(taskId);
    const task = response?.data;
    if (!response?.success || !task) {
      throw new Error(response?.msg || response?.message || "白底图任务进度读取失败");
    }
    if (task.task_id !== taskId || task.record_id !== recordId) {
      throw new Error("处理结果与当前任务不一致，未显示其他商品的图片");
    }
    progress.value = task.progress || 0;
    statusText.value = task.message || "";
    if (task.status === "success" || task.status === "failed") {
      return task;
    }
  }
  return null;
}
</script>

<template>
  <div class="whitebg-panel">
    <el-button
      type="primary"
      :loading="running"
      :disabled="!recordId || running || disabled"
      @click="start"
    >
      生成白底图
    </el-button>

    <el-button v-if="canShowResult && !running" @click="resultVisible = true">查看处理结果</el-button>
    <div v-if="running" class="whitebg-progress" role="status" aria-live="polite">
      <el-progress :percentage="progress" :stroke-width="6" />
      <span class="whitebg-progress-text">{{ taskRecordId && taskRecordId !== recordId ? `${taskRecordName}：` : '' }}{{ statusText }}</span>
    </div>

    <el-dialog
      v-model="resultVisible"
      :title="`白底图 — ${taskRecordName || '当前商品'}`"
      width="min(860px, 92vw)"
      align-center
      append-to-body
    >
      <p class="whitebg-summary">{{ summary }}</p>

      <div v-if="okItems.length" class="whitebg-grid">
        <div v-for="item in okItems" :key="item.name" class="whitebg-cell">
          <img :src="imageUrl(item.white_path)" :alt="item.name" />
          <div class="whitebg-cell-name">{{ item.name }}</div>
          <div v-if="item.warnings.length" class="whitebg-cell-warn">
            {{ item.warnings.join("；") }}
          </div>
        </div>
      </div>

      <div v-if="badItems.length" class="whitebg-bad">
        <div class="whitebg-bad-title">以下 {{ badItems.length }} 张没能生成白底图</div>
        <div v-for="item in badItems" :key="item.name" class="whitebg-bad-row">
          <span class="whitebg-bad-name">{{ item.name }}</span>
          <span class="whitebg-bad-reason">{{ reasonOf(item) }}</span>
        </div>
        <div class="whitebg-bad-hint">
          白底图未生成的图片可更换素材后再处理。已生成的 1:1 规格图可在商品目录的 SKU_1x1 文件夹中查看。
        </div>
      </div>

      <template #footer>
        <el-button type="primary" @click="resultVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.whitebg-panel {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  max-width: 100%;
}

.whitebg-panel > :deep(.el-button) {
  min-height: 40px;
  margin-left: 0;
}

.whitebg-panel > :deep(.el-button:focus-visible) {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.whitebg-progress {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-basis: 100%;
  justify-content: flex-end;
  min-width: 0;
}

.whitebg-progress :deep(.el-progress) {
  width: 140px;
}

.whitebg-progress-text {
  font-size: 12px;
  color: #606266;
  overflow-wrap: anywhere;
  max-width: 320px;
}

.whitebg-summary {
  margin: 0 0 14px;
  font-size: 13px;
  color: #303133;
}

.whitebg-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 12px;
}

.whitebg-cell {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 6px;
  background: #fff;
}

.whitebg-cell img {
  width: 100%;
  aspect-ratio: 1 / 1;
  object-fit: contain;
  display: block;
  background: #fafafa;
  border-radius: 4px;
}

.whitebg-cell-name {
  margin-top: 6px;
  font-size: 12px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.whitebg-cell-warn {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.4;
  color: #e6a23c;
}

.whitebg-bad {
  margin-top: 16px;
  padding: 12px;
  border-radius: 6px;
  background: #fef6f6;
  border: 1px solid #fde2e2;
}

.whitebg-bad-title {
  font-size: 13px;
  font-weight: 600;
  color: #c45656;
  margin-bottom: 8px;
}

.whitebg-bad-row {
  display: flex;
  gap: 10px;
  font-size: 12px;
  line-height: 1.8;
  color: #606266;
}

.whitebg-bad-name {
  flex: 0 0 150px;
  color: #303133;
}

.whitebg-bad-reason {
  flex: 1;
}

.whitebg-bad-hint {
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
</style>
