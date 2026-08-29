<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from "vue";
import { useRouter } from "vue-router";
import { ElMessage, ElMessageBox, ElLoading } from "element-plus";
import { useProductStore } from "@/stores/productStore";
import { CATEGORY_OPTIONS } from "@/types";
import type { SKU, PricingResult, PricingStatistics } from "@/types";
import { api } from "@/services/api";
import SkuList from "@/components/SkuList.vue";
import CaptureSection from "@/components/CaptureSection.vue";
import ContextMenu from "@/components/ContextMenu.vue";

const productStore = useProductStore();
const router = useRouter();

// 表单数据
const formData = ref({
  title: "",
  remark: "",
  repo: null as number | null,
  clazz: null as number | null,
  price: null as number | null,
});

// 字数统计
const titleLength = computed(() => formData.value.title?.length || 0);

// 右键菜单
const contextMenuVisible = ref(false);
const contextMenuPosition = ref({ x: 0, y: 0 });
const contextMenuProductId = ref<number | null>(null);

// 设置弹窗

// 选中的SKU
const selectedSkuPaths = ref<Set<string>>(new Set());
let autoSelectingFirstProduct = false;
const activeUploadTaskId = ref<string | null>(null);
const activeUploadTaskOrigin = ref<"local" | "external" | null>(null);
const isUploadMonitoring = computed(() => Boolean(activeUploadTaskId.value));

let uploadMonitorTimer: number | null = null;
let uploadDiscoveryTimer: number | null = null;
let uploadMonitorStartedAt = 0;
// 连续获取上传状态失败的次数（仅统计传输层异常，不代表上传本身失败）
let uploadPollFailureCount = 0;
let uploadLoading: ReturnType<typeof ElLoading.service> | null = null;
let lastExternalUploadNoticeId: string | null = null;

const uploadStatusText = ref("");
const uploadProgress = ref(0);
const uploadSteps = ref<Array<{ name: string; status: string; elapsed_ms: number; summary: string }>>([]);

const UPLOAD_POLL_INTERVAL_MS = 800;
const UPLOAD_DISCOVERY_INTERVAL_MS = 15000;
const UPLOAD_TIMEOUT_MS = 15 * 60 * 1000;
// 连续多少次拿不到上传状态才判定为「无法获取状态」并停止轮询
const UPLOAD_POLL_MAX_FAILURES = 5;

// 监听当前产品变化
watch(
  () => productStore.currentProduct,
  (product) => {
    if (product) {
      formData.value = {
        title: product.title || "",
        remark: product.remark || "",
        repo: product.repo,
        clazz: product.clazz,
        price: null,
      };
      selectedSkuPaths.value.clear();
    }
  }
);

async function ensureProductSelected() {
  if (autoSelectingFirstProduct) {
    return;
  }

  if (productStore.backendStatus !== "online") {
    return;
  }

  if (productStore.currentProductId || productStore.products.length === 0) {
    return;
  }

  autoSelectingFirstProduct = true;
  try {
    await productStore.loadProductDetail(productStore.products[0].id);
  } finally {
    autoSelectingFirstProduct = false;
  }
}

watch(
  () => [productStore.backendStatus, productStore.products.length, productStore.currentProductId],
  () => {
    void ensureProductSelected();
  },
  { immediate: true }
);

// 点击产品行
async function handleProductClick(productId: number) {
  await productStore.loadProductDetail(productId);
}

// 右键菜单
function handleContextMenu(event: MouseEvent, productId: number) {
  event.preventDefault();
  contextMenuPosition.value = { x: event.clientX, y: event.clientY };
  contextMenuProductId.value = productId;
  contextMenuVisible.value = true;
}

function openSettingsPage() {
  router.push("/settings");
}

function isUserCancel(error: unknown) {
  if (error === "cancel" || error === "close") {
    return true;
  }

  if (typeof error === "object" && error !== null && "action" in error) {
    const action = (error as { action?: unknown }).action;
    return action === "cancel" || action === "close";
  }

  return false;
}

async function confirmAction(
  message: string,
  title: string,
  options: Parameters<typeof ElMessageBox.confirm>[2] = {}
) {
  try {
    await ElMessageBox.confirm(message, title, options);
    return true;
  } catch (error) {
    if (isUserCancel(error)) {
      return false;
    }

    throw error;
  }
}

function collectDuplicateSkuGroups(skus: SKU[]) {
  const buckets = new Map<string, { display: string; count: number; paths: string[] }>();

  for (const sku of skus) {
    const display = String(sku?.name || "").trim();
    if (!display) continue;

    const normalized = display.replace(/\s+/g, " ").toLowerCase();
    const current = buckets.get(normalized);
    if (current) {
      current.count += 1;
      current.paths.push(sku.path);
    } else {
      buckets.set(normalized, { display, count: 1, paths: [sku.path] });
    }
  }

  return Array.from(buckets.values()).filter((item) => item.count > 1);
}

const duplicateSkuGroups = computed(() => collectDuplicateSkuGroups(productStore.currentSkus));

const duplicateSkuPaths = computed(() => {
  const paths = new Set<string>();
  duplicateSkuGroups.value.forEach((group) => {
    group.paths.forEach((path) => paths.add(path));
  });
  return paths;
});

function showDuplicateSkuAlert(actionText: string, groups: Array<{ display: string; count: number }>) {
  const preview = groups
    .slice(0, 3)
    .map((group) => `${group.display} x${group.count}`)
    .join("、");
  const suffix = groups.length > 3 ? ` 等 ${groups.length} 组` : "";
  ElMessage.warning({
    message: `发现重复规格，先改一下再${actionText}${preview ? `：${preview}${suffix}` : ""}`,
    showClose: true,
    duration: 0,
  });
}

async function handleContextMenuAction(action: string) {
  contextMenuVisible.value = false;
  if (!contextMenuProductId.value) return;

  if (action === "open") {
    await api.openProduct(contextMenuProductId.value);
  } else if (action === "delete") {
    const confirmed = await confirmAction("确定删除该产品吗？", "提示", {
      type: "warning",
    });
    if (!confirmed) return;

    const success = await productStore.deleteProduct(
      contextMenuProductId.value
    );
    if (success) {
      ElMessage.success("删除成功");
    }
  }
}

// 保存
async function handleSave() {
  if (!productStore.currentProductId) {
    ElMessage.warning("请先选择一个产品");
    return;
  }

  const duplicateGroups = duplicateSkuGroups.value;
  if (duplicateGroups.length > 0) {
    await showDuplicateSkuAlert("保存", duplicateGroups);
    return;
  }

  // 构建SKU数据
  const skuData: Record<string, string | number> = {
    attr_size: productStore.currentSkus.length,
  };

  productStore.currentSkus.forEach((sku, index) => {
    skuData[`attr_path_${index + 1}`] = sku.path;
    skuData[`attr_name_${index + 1}`] = sku.name;
    skuData[`attr_price_${index + 1}`] = sku.price;
  });

  const success = await productStore.saveProduct({
    ...formData.value,
    ...skuData,
  } as any);

  if (success) {
    ElMessage.success("保存成功");
  } else {
    ElMessage.error("保存失败");
  }
}

// 简单填充价格
function handleSimpleFill() {
  if (!formData.value.price) {
    ElMessage.warning("请输入价格");
    return;
  }

  const targetSkus =
    selectedSkuPaths.value.size > 0
      ? productStore.currentSkus.filter((sku) =>
          selectedSkuPaths.value.has(sku.path)
        )
      : productStore.currentSkus;

  targetSkus.forEach((sku) => {
    sku.price = formData.value.price!;
  });

  ElMessage.success("价格填充完成");
}

// 智能填充价格（基于成本项目计算）
const smartFillLoading = ref(false);
const pricingResultsVisible = ref(false);

const pricingResultsData = ref<{
  results: PricingResult[];
  statistics: PricingStatistics;
  configUsed: {
    target_gross_margin: number;
    fixed_costs: number;
    percentage_costs: number;
    cost_items_count: number;
  };
  unitPrice: number;
}>({
  results: [],
  statistics: { total_skus: 0, average_price: 0, average_margin: 0, min_price: 0, max_price: 0 },
  configUsed: { target_gross_margin: 30, fixed_costs: 0, percentage_costs: 0, cost_items_count: 0 },
  unitPrice: 0,
});

async function handleSmartFill() {
  if (!productStore.currentProductId) {
    ElMessage.warning("请先选择一个产品");
    return;
  }

  if (!formData.value.price) {
    ElMessage.warning("请输入单价（每双袜子的基准价格）");
    return;
  }

  smartFillLoading.value = true;

  try {
    const response = await api.calculateSmartPrices(
      productStore.currentProductId,
      formData.value.price
    );

    if (response.success && response.data) {
      const pricingResults = response.data.pricing_results || [];

      // 根据计算结果填充价格
      pricingResults.forEach((result: PricingResult) => {
        const sku = result.sku_path
          ? productStore.currentSkus.find(s => s.path === result.sku_path)
          : productStore.currentSkus.find(s => s.name === result.sku_name);
        if (sku) {
          sku.price = result.suggested_price;
        }
      });

      // 保存结果用于弹窗显示
      const stats = response.data.statistics;
      const configUsed = response.data.config_used || {};
      pricingResultsData.value = {
        results: pricingResults,
        statistics: {
          total_skus: stats.total_skus || 0,
          average_price: stats.average_price || 0,
          average_margin: stats.average_margin || 0,
          min_price: stats.min_price || 0,
          max_price: stats.max_price || 0,
        },
        configUsed: {
          target_gross_margin: configUsed.target_gross_margin || 30,
          fixed_costs: configUsed.fixed_costs || 0,
          percentage_costs: configUsed.percentage_costs || 0,
          cost_items_count: configUsed.cost_items_count || 0,
        },
        unitPrice: formData.value.price,
      };
      
      await nextTick();
      pricingResultsVisible.value = true;
    } else {
      const errorMessage =
        (response as any)?.error ||
        (response as any)?.message ||
        "智能定价失败";
      ElMessage.error(errorMessage);
    }
  } catch (error) {
    console.error("智能填充失败:", error);
    const backendError =
      (error as any)?.response?.data?.error ||
      (error as any)?.response?.data?.message ||
      (error as any)?.message ||
      "自动填充失败，请稍后重试";
    ElMessage.error(backendError);
  } finally {
    smartFillLoading.value = false;
  }
}

// 获取利润率颜色
function getProfitColor(margin: number): string {
  if (margin >= 30) return "#27ae60"; // 绿色 - 良好
  if (margin >= 20) return "#f39c12"; // 黄色 - 一般
  return "#e74c3c"; // 红色 - 偏低
}

// 开始上传
function ensureUploadLoading(text: string) {
  if (!uploadLoading) {
    uploadLoading = ElLoading.service({
      text,
      background: "rgba(0, 0, 0, 0.35)",
    });
    return;
  }

  uploadLoading.setText(text);
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
  uploadMonitorStartedAt = 0;
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
  stopUploadMonitoring();
  await refreshAfterUpload();

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
  if (!activeUploadTaskId.value) {
    stopUploadMonitoring();
    return;
  }

  let statusResp: any;
  try {
    statusResp = await productStore.getUploadStatus(activeUploadTaskId.value);
  } catch (error) {
    // 传输层异常（超时 / 连接被拒）只说明「拿不到状态」，后台上传线程仍在继续，
    // 不能当成上传失败。连续失败达到阈值才停止轮询并如实提示。
    console.error("获取上传状态失败:", error);
    uploadPollFailureCount += 1;
    if (uploadPollFailureCount < UPLOAD_POLL_MAX_FAILURES) {
      return;
    }
    stopUploadMonitoring();
    ElMessage.error("无法获取上传状态，任务可能仍在后台运行，请勿重复发起");
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
    stopUploadMonitoring();
    ElMessage.error("上传超过 15 分钟仍未完成，请稍后重试或重新发起");
    return;
  }

  if (status === "success" || status === "failed" || status === "cancelled") {
    await handleUploadTerminal(data);
  }
}

function startUploadMonitoring(taskId: string, origin: "local" | "external", createdAt?: string | null) {
  activeUploadTaskId.value = taskId;
  activeUploadTaskOrigin.value = origin;
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
  if (activeUploadTaskOrigin.value === "local" && activeUploadTaskId.value) {
    return false;
  }

  try {
    const response = await api.getUploadTasks({
      silentError: !!options.silent,
    });
    const tasks = response.data?.tasks || [];
    const currentTaskId = response.data?.browser_status?.current_task || null;
    const activeTask =
      tasks.find((task) => task.task_id === currentTaskId) ||
      [...tasks]
        .filter((task) => task.status === "pending" || task.status === "running")
        .sort((left, right) =>
          String(right.created_at || "").localeCompare(String(left.created_at || ""))
        )[0];

    if (!activeTask) {
      return false;
    }

    const isNewExternalTask =
      activeUploadTaskOrigin.value !== "external" ||
      activeUploadTaskId.value !== activeTask.task_id;

    if (isNewExternalTask) {
      ensureUploadLoading(`检测到外部上传：${activeTask.progress}% - ${activeTask.message}`);
      startUploadMonitoring(
        activeTask.task_id,
        "external",
        activeTask.started_at || activeTask.created_at || null
      );

      if (!options.silent && lastExternalUploadNoticeId !== activeTask.task_id) {
        lastExternalUploadNoticeId = activeTask.task_id;
        ElMessage.info("检测到正在进行的上传任务，已自动接上进度");
      }
      return true;
    }

    return false;
  } catch (error) {
    if (!options.silent) {
      console.warn("同步外部上传任务失败:", error);
    }
    return false;
  }
}

function triggerExternalUploadSync() {
  if (document.visibilityState === "hidden") {
    return;
  }

  void syncExternalUploadTask({ silent: true });
}

async function handleStartUploadUnified() {
  if (isUploadMonitoring.value) {
    ElMessage.warning("已有上传任务在进行中，请等完成后再开始");
    return;
  }

  const recordId = productStore.currentProductId;
  if (!recordId) {
    ElMessage.error("请先在列表中选中一个产品再开始上传");
    return;
  }

  const duplicateGroups = collectDuplicateSkuGroups(productStore.currentSkus);
  if (duplicateGroups.length > 0) {
    await showDuplicateSkuAlert("上传", duplicateGroups);
    return;
  }

  ensureUploadLoading("正在启动上传…");

  try {
    const response = await productStore.startUpload(recordId);
    if (!response.success) {
      closeUploadLoading();
      ElMessage.error(response.msg || "上传启动失败，请稍后重试");
      return;
    }

    const taskId = (response as any)?.data?.task_id as string | undefined;
    if (!taskId) {
      closeUploadLoading();
      ElMessage.error("上传启动失败：未获取到任务编号，请重试");
      return;
    }

    startUploadMonitoring(taskId, "local");
  } catch (error) {
    closeUploadLoading();
    ElMessage.error("上传失败，请稍后重试");
  }
}

function handleCancelSelect() {
  selectedSkuPaths.value.clear();
  ElMessage.success("已取消选择");
}

// 清空全部
async function handleDeleteAll() {
  const confirmed = await confirmAction(
    "确定清空所有产品吗？此操作不可恢复！",
    "警告",
    {
    type: "warning",
    confirmButtonText: "确定清空",
    cancelButtonText: "取消",
    }
  );
  if (!confirmed) return;

  const success = await productStore.deleteAll();
  if (success) {
    ElMessage.success("已清空所有产品");
  } else {
    ElMessage.error("清空失败");
  }
}

// SKU选中切换
function handleSkuSelect(sku: SKU) {
  if (selectedSkuPaths.value.has(sku.path)) {
    selectedSkuPaths.value.delete(sku.path);
  } else {
    selectedSkuPaths.value.add(sku.path);
  }
}

// SKU删除
async function handleSkuDelete(sku: SKU) {
  const confirmed = await confirmAction("确定删除该SKU吗？", "提示", {
    type: "warning",
  });
  if (!confirmed) return;

  const success = await productStore.deleteSku(sku.path);
  if (success) {
    ElMessage.success("删除成功");
  } else {
    ElMessage.error("删除失败");
  }
}

onMounted(() => {
  void syncExternalUploadTask({ silent: true });
  window.addEventListener("focus", triggerExternalUploadSync);
  document.addEventListener("visibilitychange", triggerExternalUploadSync);
  uploadDiscoveryTimer = window.setInterval(() => {
    triggerExternalUploadSync();
  }, UPLOAD_DISCOVERY_INTERVAL_MS);
});

onUnmounted(() => {
  if (uploadDiscoveryTimer !== null) {
    window.clearInterval(uploadDiscoveryTimer);
    uploadDiscoveryTimer = null;
  }
  window.removeEventListener("focus", triggerExternalUploadSync);
  document.removeEventListener("visibilitychange", triggerExternalUploadSync);
  stopUploadMonitoring();
});
</script>

<template>
  <div class="product-manager fade-in">
    <!-- 左侧面板 -->
    <div class="left-panel">
      <!-- 链接采集区域 -->
      <CaptureSection @imported="productStore.fetchProducts()" />

      <!-- 产品列表 -->
      <div class="product-list">
        <h2 class="panel-title">待上传目录</h2>

        <el-scrollbar class="product-scroll">
          <div
            v-for="product in productStore.products"
            :key="product.id"
            class="product-item"
            :class="{ active: product.id === productStore.currentProductId }"
            @click="handleProductClick(product.id)"
            @contextmenu="handleContextMenu($event, product.id)"
          >
            <div class="product-icon">📁</div>
            <div class="product-info">
              <span class="product-name">{{ product.name }}</span>
              <span class="product-time">{{ product.update_time }}</span>
            </div>
          </div>

          <div v-if="productStore.products.length === 0" class="empty-tip">
            暂无产品，请拖入文件夹或采集链接
          </div>
        </el-scrollbar>
      </div>
    </div>

    <!-- 右侧表单 -->
    <div class="right-panel" v-loading="productStore.detailLoading">
      <h1 class="form-title">
        {{ productStore.currentProduct?.name || "XXX" }}的配置
      </h1>

      <el-form label-position="top" class="product-form">
        <!-- 类目选择 -->
        <el-form-item>
          <el-select
            v-model="formData.clazz"
            placeholder="请选择类目"
            class="full-width"
          >
            <el-option
              v-for="option in CATEGORY_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>

        <!-- 商品标题 -->
        <el-form-item>
            <div class="title-input-wrapper">
              <el-input
                v-model="formData.title"
              placeholder="标题"
              class="title-input"
              />
            <span class="word-count" :class="{ 'over-limit': titleLength > 60 }">
              {{ titleLength }}/60
            </span>
          </div>
        </el-form-item>

        <!-- 卖点备注 -->
        <el-form-item>
          <el-input v-model="formData.remark" placeholder="卖点添加/备注说明" />
        </el-form-item>

        <!-- 库存和价格 -->
        <el-form-item>
          <div class="price-row">
            <el-input
              v-model.number="formData.repo"
              type="number"
              placeholder="设置库存"
              class="repo-input"
            />
            <el-input
              v-model.number="formData.price"
              type="number"
              placeholder="单价"
              class="price-input"
            />
            <el-button type="warning" @click="handleSimpleFill">
              填充
            </el-button>
            <el-button type="success" @click="handleSmartFill" :loading="smartFillLoading">
              智能填充
            </el-button>
            <el-button type="primary" @click="handleSave">保存</el-button>
          </div>
        </el-form-item>

        <!-- SKU列表 -->
        <SkuList
          :skus="productStore.currentSkus"
          :selected-paths="selectedSkuPaths"
          :duplicate-paths="duplicateSkuPaths"
          @select="handleSkuSelect"
          @delete="handleSkuDelete"
        />

        <!-- 上传进度 -->
        <div v-if="isUploadMonitoring" class="upload-status">
          <div class="status-header">
            <div class="status-spinner"></div>
            <span class="status-text">{{ uploadStatusText }}</span>
            <span class="status-pct">{{ uploadProgress }}%</span>
          </div>
          <div class="status-progress-bar">
            <div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div>
          </div>
          <div v-if="uploadSteps.length > 0" class="status-steps">
            <div
              v-for="(step, i) in uploadSteps"
              :key="i"
              class="step-item"
              :class="'step-' + step.status"
            >
              <span class="step-icon">{{ step.status === 'ok' ? '✓' : step.status === 'failed' ? '✗' : '○' }}</span>
              <span class="step-name">{{ step.name }}</span>
              <span class="step-time">{{ step.elapsed_ms }}ms</span>
              <span v-if="step.summary" class="step-summary">{{ step.summary }}</span>
            </div>
          </div>
        </div>

        <!-- 底部按钮 -->
        <div class="action-buttons">
          <el-button type="primary" :disabled="isUploadMonitoring" @click="handleStartUploadUnified">
            开始上传
          </el-button>
          <el-button type="warning" @click="handleCancelSelect">
            取消勾选
          </el-button>
          <el-button type="danger" @click="handleDeleteAll">
            清空全部
          </el-button>
          <el-button type="info" @click="openSettingsPage">
            ⚙️ 设置
          </el-button>
        </div>
      </el-form>
    </div>

    <!-- 右键菜单 -->
    <ContextMenu
      v-model:visible="contextMenuVisible"
      :position="contextMenuPosition"
      @action="handleContextMenuAction"
    />

    <!-- 智能填充结果弹窗 -->
    <el-dialog
      v-model="pricingResultsVisible"
      title="📊 智能填充成本分析结果"
      width="1200px"
      top="5vh"
      class="pricing-results-dialog"
      :lock-scroll="false"
      :close-on-click-modal="false"
      destroy-on-close
      center
    >
      <!-- 配置与统计信息 -->
      <div class="config-info">
        <span class="config-tag">🎯 目标毛利率: {{ pricingResultsData.configUsed.target_gross_margin }}%</span>
        <span class="config-tag">💰 单价: ¥{{ pricingResultsData.unitPrice.toFixed(2) }}/双</span>
        <span class="config-tag">📦 固定: ¥{{ pricingResultsData.configUsed.fixed_costs.toFixed(2) }}</span>
        <span class="config-tag">💳 百分比: {{ pricingResultsData.configUsed.percentage_costs }}%</span>
        <span class="config-tag divider">|</span>
        <span class="config-tag success">✅ {{ pricingResultsData.statistics.total_skus }}个SKU</span>
        <span class="config-tag info">📊 均价¥{{ pricingResultsData.statistics.average_price.toFixed(2) }}</span>
        <span class="config-tag profit">📈 区间¥{{ pricingResultsData.statistics.min_price.toFixed(2) }}-{{ pricingResultsData.statistics.max_price.toFixed(2) }}</span>
      </div>
      
      <!-- 详细表格 - 支持水平滚动 -->
      <div class="table-scroll-wrapper">
        <el-table 
          :data="pricingResultsData.results" 
          stripe
          border
          max-height="350"
          class="pricing-table"
          size="small"
          table-layout="fixed"
        >
          <el-table-column prop="sku_name" label="SKU名称" min-width="150">
            <template #default="{ row }">
              <span class="sku-name-cell">{{ row.sku_name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" align="center">
            <template #default="{ row }">
              <span class="quantity-cell">{{ row.quantity }}</span>
            </template>
          </el-table-column>
          <el-table-column label="单价" align="center">
            <template #default="{ row }">
              <span class="unit-price-cell">¥{{ (row.sock_cost / row.quantity).toFixed(2) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="袜子成本" align="center">
            <template #default="{ row }">
              <span class="cost-cell">¥{{ row.sock_cost?.toFixed(2) || '0.00' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="固定成本" align="center">
            <template #default="{ row }">
              <span class="fixed-cost-cell">¥{{ row.fixed_costs?.toFixed(2) || '0.00' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="百分比成本" align="center">
            <template #default="{ row }">
              <span class="percentage-cost-cell">¥{{ row.percentage_cost?.toFixed(2) || '0.00' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="总成本" align="center">
            <template #default="{ row }">
              <span class="total-cost-cell">¥{{ row.total_cost?.toFixed(2) || '0.00' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="suggested_price" label="建议售价" align="center">
            <template #default="{ row }">
              <span class="suggested-price">¥{{ row.suggested_price?.toFixed(2) || '0.00' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="毛利率" align="center">
            <template #default="{ row }">
              <span 
                class="profit-margin"
                :style="{ color: getProfitColor(row.profit_margin || 0) }"
              >
                {{ row.profit_margin?.toFixed(1) || '0.0' }}%
              </span>
            </template>
          </el-table-column>
          <el-table-column label="利润" align="center">
            <template #default="{ row }">
              <span 
                class="profit-amount"
                :style="{ color: (row.profit || 0) >= 0 ? '#27ae60' : '#e74c3c' }"
              >
                ¥{{ row.profit?.toFixed(2) || '0.00' }}
              </span>
            </template>
          </el-table-column>
        </el-table>
      </div>
      
      <!-- 说明 -->
      <div class="pricing-tips">
        <p><strong>💡 成本计算公式：</strong></p>
        <ul>
          <li><strong>总成本</strong> = 袜子成本 + 固定成本 + 百分比成本</li>
          <li><strong>建议售价</strong> = 总成本 ÷ (1 - 目标毛利率 - 百分比成本率)</li>
          <li><strong>毛利率颜色</strong>：<span style="color:#27ae60">绿色≥30%</span> | <span style="color:#f39c12">黄色≥20%</span> | <span style="color:#e74c3c">红色&lt;20%</span></li>
        </ul>
        <p class="tip-note">💡 可在「设置」中调整成本项目和目标毛利率</p>
      </div>
      
      <template #footer>
        <div class="dialog-footer">
          <el-button type="primary" @click="pricingResultsVisible = false">
            确定
          </el-button>
        </div>
      </template>
    </el-dialog>

  </div>
</template>

<style lang="scss" scoped>
.product-manager {
  display: flex;
  height: 100vh;
  padding: var(--container-padding);
  gap: var(--container-padding);
}

// 左侧面板
.left-panel {
  width: var(--left-panel-width);
  background: var(--card-background);
  border: 1px solid var(--border-color-white);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: all var(--transition-base) ease;

  &:hover {
    background: var(--card-background-hover);
    box-shadow: var(--shadow-xl);
  }
}

.product-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 10px 20px;
}

.panel-title {
  text-align: center;
  font-weight: 700;
  padding: 15px 0;
  color: var(--text-primary);
  font-size: var(--font-size-xl);
  position: relative;

  &::after {
    content: "";
    position: absolute;
    bottom: 8px;
    left: 50%;
    transform: translateX(-50%);
    width: 40px;
    height: 2px;
    background: var(--primary-gradient);
    border-radius: 1px;
  }
}

.product-scroll {
  flex: 1;
}

.product-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 12px;
  margin: 2px 0;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base) ease;

  &:hover {
    background: rgba(92, 124, 250, 0.08);

    .product-name {
      color: var(--primary-color);
    }
  }

  &:active {
    transform: scale(0.99);
    background: rgba(92, 124, 250, 0.12);
  }

  &.active {
    background: linear-gradient(
      90deg,
      rgba(92, 124, 250, 0.15) 0%,
      rgba(92, 124, 250, 0.06) 100%
    );
    border-radius: var(--radius-sm);

    .product-name {
      color: var(--primary-color);
      font-weight: 600;
    }
  }
}

.product-icon {
  font-size: 16px;
}

.product-info {
  flex: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.product-name {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  font-weight: 500;
}

.product-time {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.empty-tip {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 20px;
  font-size: var(--font-size-sm);
}

// 右侧面板
.right-panel {
  flex: 1;
  background: var(--card-background);
  border: 1px solid var(--border-color-white);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--container-padding);
  display: flex;
  flex-direction: column;
  overflow: hidden;  // 保持内容不溢出
}

.form-title {
  text-align: center;
  margin-bottom: 24px;
  color: var(--text-primary);
  font-weight: 700;
  font-size: var(--font-size-title);
  position: relative;
  padding-bottom: 15px;

  &::after {
    content: "";
    position: absolute;
    bottom: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 60px;
    height: 2px;
    background: var(--primary-gradient);
    border-radius: 1px;
  }
}

.product-form {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;  // 保持内容不溢出
  min-height: 0;  // 重要：允许flex容器收缩
  
  // 让表单项不要收缩
  :deep(.el-form-item) {
    flex-shrink: 0;
  }
  
  // 让SKU列表区域可滚动并填充剩余空间
  :deep(.sku-list-container) {
    flex: 1;
    min-height: 0;  // 重要：允许flex子项收缩
    overflow: hidden;
  }
}

.full-width {
  width: 100%;
}

.title-input-wrapper {
  position: relative;
  width: 100%;

  .title-input {
    :deep(.el-input__inner) {
      padding-right: 60px;
    }
  }

  .word-count {
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    color: #999;
    font-size: 12px;
    pointer-events: none;

    &.over-limit {
      color: red;
    }
  }
}

.price-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;

  .repo-input {
    width: 103px;
  }

  .price-input {
    width: 100px;
  }
}

.action-buttons {
  display: flex;
  gap: var(--button-gap);
  padding-top: var(--container-padding);
  margin-top: auto;
  flex-shrink: 0;  // 不允许收缩，始终显示
}

// 上传步骤进度
.upload-status {
  background: #f8f9fc;
  border: 1px solid #e4e7ed;
  border-radius: var(--radius-sm, 8px);
  padding: 12px 16px;
  margin-top: 12px;

  .status-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .status-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid #e4e7ed;
    border-top-color: #5c7cfa;
    border-radius: 50%;
    animation: upload-spin 0.8s linear infinite;
  }

  @keyframes upload-spin {
    to { transform: rotate(360deg); }
  }

  .status-text {
    flex: 1;
    font-size: 13px;
    color: #303133;
  }

  .status-pct {
    font-size: 12px;
    color: #909399;
  }

  .status-progress-bar {
    height: 4px;
    background: #e4e7ed;
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 8px;

    .progress-fill {
      height: 100%;
      background: #5c7cfa;
      border-radius: 2px;
      transition: width 0.3s ease;
    }
  }

  .status-steps {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .step-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    padding: 3px 6px;
    border-radius: 4px;

    &.step-ok {
      color: #67c23a;
      background: rgba(103, 194, 58, 0.06);
    }

    &.step-failed {
      color: #f56c6c;
      background: rgba(245, 108, 108, 0.06);
    }

    &.step-running {
      color: #5c7cfa;
      background: rgba(92, 124, 250, 0.06);
    }
  }

  .step-icon {
    width: 16px;
    text-align: center;
    font-weight: bold;
  }

  .step-name {
    min-width: 100px;
    font-weight: 500;
  }

  .step-time {
    color: #909399;
    font-size: 11px;
  }

  .step-summary {
    color: #606266;
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 200px;
  }
}
</style>

<style lang="scss">
// 智能填充结果弹窗
.pricing-results-dialog {
  :deep(.el-dialog) {
    max-height: 90vh;
    display: flex;
    flex-direction: column;
  }
  
  :deep(.el-dialog__header) {
    padding: 16px 20px;
    border-bottom: 1px solid #ebeef5;
    margin-right: 0;
  }
  
  :deep(.el-dialog__body) {
    padding: 16px 20px;
    flex: 1;
    overflow-y: auto;
  }
  
  :deep(.el-dialog__footer) {
    padding: 12px 20px;
    border-top: 1px solid #ebeef5;
  }
}

.config-info {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 12px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(92, 124, 250, 0.08) 0%, rgba(92, 124, 250, 0.03) 100%);
  border-radius: 8px;
  border: 1px solid rgba(92, 124, 250, 0.15);
  
  .config-tag {
    font-size: 13px;
    color: #5c7cfa;
    font-weight: 500;
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.6);
    border-radius: 4px;
    
    &.divider {
      background: transparent;
      color: rgba(92, 124, 250, 0.3);
      padding: 0 4px;
    }
    
    &.success {
      color: #27ae60;
      background: rgba(39, 174, 96, 0.1);
    }
    
    &.info {
      color: #3498db;
      background: rgba(52, 152, 219, 0.1);
    }
    
    &.profit {
      color: #9b59b6;
      background: rgba(155, 89, 182, 0.1);
    }
  }
}

.pricing-summary {
  display: none;  // 已合并到 config-info
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  
  .summary-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 13px;
    
    .label {
      color: #6c757d;
      font-size: 12px;
    }
    
    .value {
      font-weight: 600;
      font-size: 14px;
    }
    
    &.success {
      background: rgba(39, 174, 96, 0.1);
      .value { color: #27ae60; }
    }
    
    &.info {
      background: rgba(52, 152, 219, 0.1);
      .value { color: #3498db; }
    }
    
    &.profit {
      background: rgba(155, 89, 182, 0.1);
      .value { color: #9b59b6; }
    }
    
    &.warning {
      background: rgba(230, 126, 34, 0.1);
      .value { color: #e67e22; }
    }
  }
}

// 表格滚动容器
.table-scroll-wrapper {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  
  // 美化滚动条
  &::-webkit-scrollbar {
    height: 8px;
  }
  
  &::-webkit-scrollbar-track {
    background: #f1f1f1;
    border-radius: 4px;
  }
  
  &::-webkit-scrollbar-thumb {
    background: #c1c1c1;
    border-radius: 4px;
    
    &:hover {
      background: #a8a8a8;
    }
  }
}

.pricing-table {
  font-size: 12px;
  width: 100%;
  min-width: 1080px;
  
  :deep(.el-table__header th) {
    background-color: #f8f9fa !important;
    font-weight: 600;
    color: #495057;
    padding: 8px 12px;
    white-space: nowrap; // 表头不换行
  }
  
  :deep(.el-table__row td) {
    padding: 6px 12px;
  }
  
  :deep(.el-table__cell) {
    white-space: nowrap; // 单元格内容不换行
  }
  
  .sku-name-cell {
    white-space: nowrap;
    font-weight: 500;
  }
  
  .quantity-cell {
    color: #6c757d;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .unit-price-cell {
    color: #2ecc71;
    font-weight: 600;
    font-size: 12px;
    white-space: nowrap;
  }
  
  .cost-cell {
    color: #3498db;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .fixed-cost-cell {
    color: #17a2b8;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .percentage-cost-cell {
    color: #6f42c1;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .total-cost-cell {
    color: #495057;
    font-weight: 700;
    white-space: nowrap;
  }
  
  .suggested-price {
    color: #e67e22;
    font-weight: bold;
    font-size: 13px;
    white-space: nowrap;
  }
  
  .profit-margin {
    font-weight: bold;
    white-space: nowrap;
  }
  
  .profit-amount {
    font-weight: bold;
    white-space: nowrap;
  }
}

.pricing-tips {
  margin-top: 14px;
  padding: 12px 14px;
  background: rgba(39, 174, 96, 0.06);
  border-radius: 6px;
  border-left: 3px solid #27ae60;
  font-size: 12px;
  color: #2d5a2d;
  line-height: 1.5;
  
  p {
    margin: 0 0 6px;
  }
  
  ul {
    margin: 0;
    padding-left: 18px;
    
    li {
      margin-bottom: 3px;
    }
  }
  
  .tip-note {
    margin-top: 8px;
    color: #5c7cfa;
    font-style: italic;
  }
}
</style>
