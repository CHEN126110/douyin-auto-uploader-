<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick, h } from "vue";
import { useRouter } from "vue-router";
import axios from "axios";
import { ElMessage, ElMessageBox, ElLoading, ElButton } from "element-plus";
import { useProductStore } from "@/stores/productStore";
import { CATEGORY_OPTIONS } from "@/types";
import { countTaobaoTitleUnits } from "@/utils/taobaoTextLength";
import { isVerifiedTaobaoFillResult } from "@/utils/taobaoFormVerification";
import type {
  SKU,
  PricingResult,
  PricingStatistics,
  PublishSubmitMode,
  ShopSessionState,
  ApiResponse,
  TaobaoProductRequest,
  TargetPublishPlatform,
} from "@/types";
import { api } from "@/services/api";
import SkuList from "@/components/SkuList.vue";
import CaptureSection from "@/components/CaptureSection.vue";
import ContextMenu from "@/components/ContextMenu.vue";
import ShopStatusBar from "@/components/ShopStatusBar.vue";
import ProductMediaManager from "@/components/ProductMediaManager.vue";

const productStore = useProductStore();
const router = useRouter();

const shopStatusBarRef = ref<InstanceType<typeof ShopStatusBar> | null>(null);
const shopSession = ref<ShopSessionState | null>(null);

// 提交方式：'publish' 直接提交上架，'stop' 全部填好后停下不提交。
// 读不到设置时保守取 stop——发布不可撤销，宁可让用户手动确认一次。
const publishSubmitMode = ref<PublishSubmitMode>("stop");

function handleShopSessionChanged(state: ShopSessionState | null) {
  shopSession.value = state;
  productStore.setShopSession(state);
}

async function loadPublishSubmitMode() {
  try {
    const response = await api.getSettings();
    const resolved = response?.data?.settings?.automation_config?.publish_submit_mode_effective;
    publishSubmitMode.value = resolved === "publish" ? "publish" : "stop";
  } catch (error) {
    publishSubmitMode.value = "stop";
  }
}

// 表单数据
const formData = ref({
  title: "",
  remark: "",
  repo: null as number | null,
  clazz: null as number | null,
  price: null as number | null,
});

// 字数统计
const titleLength = computed(() => productStore.targetPublishPlatform === "taobao"
  ? countTaobaoTitleUnits(formData.value.title || "")
  : formData.value.title?.length || 0);

// 右键菜单
const contextMenuVisible = ref(false);
const contextMenuPosition = ref({ x: 0, y: 0 });
const contextMenuProductId = ref<number | null>(null);
const mediaManagerVisible = ref(false);
const mediaManagerProductId = ref<number | null>(null);

function handleProductMenuKey(event: KeyboardEvent, productId: number) {
  if (uploadBusy.value) return;
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
  contextMenuProductId.value = productId;
  contextMenuPosition.value = { x: rect.left + 20, y: rect.bottom };
  contextMenuVisible.value = true;
}

// 设置弹窗

// 选中的SKU
const selectedSkuPaths = ref<Set<string>>(new Set());
let autoSelectingFirstProduct = false;
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
const shopAccountBusy = ref(false);
const uploadTaskCancelling = ref(false);
const publishPlatformLabel = computed(() =>
  productStore.targetPublishPlatform === "douyin" ? "抖音" :
    productStore.targetPublishPlatform === "taobao" ? "淘宝" : ""
);
const publishActionText = computed(() => `开始${publishPlatformLabel.value}发布`);
const publishButtonDisabled = computed(() =>
  !productStore.targetPublishPlatform || isUploadMonitoring.value ||
    isUploadStarting.value || Boolean(taobaoUnknownStart.value) || shopAccountBusy.value ||
    productStore.detailLoading
);

let uploadMonitorTimer: number | null = null;
let uploadDiscoveryTimer: number | null = null;
let uploadMonitorStartedAt = 0;
// 连续获取上传状态失败的次数（仅统计传输层异常，不代表上传本身失败）
let uploadPollFailureCount = 0;
let uploadPollInFlight = false;
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
const uploadSteps = ref<Array<{ name: string; label?: string; status: string; elapsed_ms?: number; summary?: string }>>([]);

const UPLOAD_POLL_INTERVAL_MS = 800;
const UPLOAD_DISCOVERY_INTERVAL_MS = 15000;
const UPLOAD_TIMEOUT_MS = 15 * 60 * 1000;
// 连续多少次拿不到上传状态才判定为「无法获取状态」并停止轮询
const UPLOAD_POLL_MAX_FAILURES = 5;

// 监听当前产品变化
watch(
  () => productStore.currentProduct,
  (product) => {
    formData.value = product
      ? {
        title: product.title || "",
        remark: product.remark || "",
        repo: product.repo,
        clazz: product.clazz,
        price: null,
      }
      : { title: "", remark: "", repo: null, clazz: null, price: null };
    selectedSkuPaths.value.clear();
  },
  { immediate: true }
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
  if (uploadBusy.value || productStore.detailLoading) return;
  await productStore.loadProductDetail(productId);
}

// 右键菜单
function handleContextMenu(event: MouseEvent, productId: number) {
  event.preventDefault();
  if (uploadBusy.value) return;
  contextMenuPosition.value = { x: event.clientX, y: event.clientY };
  contextMenuProductId.value = productId;
  contextMenuVisible.value = true;
}

function openSettingsPage() {
  if (uploadBusy.value) return;
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
  if (uploadBusy.value) return;
  contextMenuVisible.value = false;
  if (!contextMenuProductId.value) return;

  if (action === "media") {
    mediaManagerProductId.value = contextMenuProductId.value;
    mediaManagerVisible.value = true;
  } else if (action === "open") {
    await api.openProduct(contextMenuProductId.value);
  } else if (action === "delete") {
    const confirmed = await confirmAction(
      "确定删除该产品吗？采集商品的整个本地文件夹（含主图、SKU、详情页）会一起移入回收站；手动导入的原始文件保留。",
      "删除产品", {
      type: "warning",
    });
    if (!confirmed) return;

    const success = await productStore.deleteProduct(
      contextMenuProductId.value
    );
    if (success) {
      ElMessage.success("删除成功");
    } else {
      ElMessage.error(`删除失败：${productStore.lastActionError || "未知原因"}`);
    }
  }
}

function productSaveData(form: typeof formData.value, skus: SKU[]) {
  const data: Record<string, string | number | null> = {
    title: form.title.trim(), remark: form.remark,
    repo: form.repo, clazz: form.clazz, attr_size: skus.length,
  };
  skus.forEach((sku, index) => {
    data[`attr_path_${index + 1}`] = sku.path;
    data[`attr_name_${index + 1}`] = sku.name.trim();
    data[`attr_price_${index + 1}`] = sku.price;
  });
  return data;
}

function capturePublishSnapshot(platform: TargetPublishPlatform) {
  const recordId = productStore.currentProductId;
  const record = productStore.currentProduct;
  const account = productStore.currentShopSession;
  if (!recordId || record?.id !== recordId) {
    ElMessage.warning("请先选择并加载一个商品");
    return null;
  }
  if (account?.platform !== platform || !account.active_profile) {
    ElMessage.warning("请先选择对应平台的店铺账户");
    return null;
  }
  const form = { ...formData.value, title: formData.value.title.trim() };
  const skus = productStore.currentSkus.map((sku) => ({ ...sku, name: sku.name.trim() }));
  if (!form.title || !CATEGORY_OPTIONS.some(option => option.value === form.clazz) ||
      typeof form.repo !== "number" || !Number.isInteger(form.repo) || form.repo < 0) {
    ElMessage.warning("请填写当前商品标题、商品种类和有效的整数库存");
    return null;
  }
  if (!skus.length || skus.some(sku => !sku.name || typeof sku.price !== "number" ||
      !Number.isFinite(sku.price) || sku.price <= 0)) {
    ElMessage.warning("请填写全部规格名称及大于 0 的有效售价");
    return null;
  }
  return { recordId, recordName: record.name, platform, accountProfile: account.active_profile,
    form, skus, saveData: productSaveData(form, skus) };
}

function publishContextUnchanged(snapshot: NonNullable<ReturnType<typeof capturePublishSnapshot>>) {
  const account = productStore.currentShopSession;
  return productStore.currentProductId === snapshot.recordId &&
    productStore.currentProduct?.id === snapshot.recordId &&
    account?.platform === snapshot.platform && account.active_profile === snapshot.accountProfile;
}

async function savePublishSnapshot(snapshot: NonNullable<ReturnType<typeof capturePublishSnapshot>>) {
  if (!publishContextUnchanged(snapshot)) {
    ElMessage.error("所选商品或店铺已改变，未启动本次上传");
    return false;
  }
  const saved = await productStore.saveProduct(snapshot.saveData as any, {
    recordId: snapshot.recordId, publishPlatform: snapshot.platform, accountProfile: snapshot.accountProfile,
  });
  if (!saved) {
    ElMessage.error(`上传前保存失败：${productStore.lastActionError || "未确认商品资料已保存"}`);
    return false;
  }
  if (!publishContextUnchanged(snapshot)) {
    ElMessage.error("所选商品或店铺已改变，未启动本次上传");
    return false;
  }
  return saved.record_revision;
}

// 保存
async function handleSave() {
  if (uploadBusy.value) return;
  if (!productStore.currentProductId) {
    ElMessage.warning("请先选择一个产品");
    return;
  }

  const duplicateGroups = duplicateSkuGroups.value;
  if (duplicateGroups.length > 0) {
    await showDuplicateSkuAlert("保存", duplicateGroups);
    return;
  }

  const recordId = productStore.currentProductId;
  const success = await productStore.saveProduct(productSaveData(formData.value, productStore.currentSkus) as any,
    { recordId });

  if (success) {
    ElMessage.success("保存成功");
  } else {
    ElMessage.error(`保存失败：${productStore.lastActionError || "未知原因"}`);
  }
}

// 简单填充价格
function handleSimpleFill() {
  if (uploadBusy.value) return;
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
  if (uploadBusy.value) return;
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
  if (uploadPollInFlight) return;
  uploadPollInFlight = true;
  try {
    await pollUploadTaskOnce();
  } finally {
    uploadPollInFlight = false;
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
      : await api.cancelUpload(taskId);
    if (!response.success) throw new Error(response.message || response.msg || "后端未接受取消请求");
    ElMessage.info("已请求取消，将在当前阶段结束后停止");
    void retryUploadProgress();
  } catch (error) {
    const reason = axios.isAxiosError<ApiResponse>(error)
      ? error.response?.data?.message || error.response?.data?.msg || error.message
      : error instanceof Error ? error.message : String(error);
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

/** 把外部来源的文本转义后再放进弹窗 HTML：店铺名来自平台接口，不能当代码用。 */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * 真实发布前的人工确认。
 *
 * 商品一旦提交就直接上架，撤不回来，所以必须有一次明确的确认；
 * 同时把实测到的店铺摆在确认框里——发错店是这里唯一无法挽回的错误。
 */
async function confirmRealPublish(): Promise<boolean> {
  await shopStatusBarRef.value?.refresh(true, true);
  const state = shopSession.value;

  const lines: string[] = [];
  if (state?.status === "logged_in" && state.shop_id) {
    // 店名取不到时退回店铺编号：宁可显示得朴素，也要让人确认得了发给谁。
    const name = escapeHtml(state.shop_name || `店铺 ${state.shop_id}`);
    lines.push(`<div>将发布到：<b>${name}</b></div>`);
  } else {
    lines.push(
      "<div style=\"color:#9a5b00\">当前读不到已登录的店铺，无法确认会发布到哪个店。建议先完成登录再发布。</div>"
    );
  }
  lines.push("<div style=\"margin-top:8px\">商品提交后会直接上架，无法撤销。</div>");

  return await confirmAction(lines.join(""), "确认发布", {
    type: "warning",
    dangerouslyUseHTMLString: true,
    confirmButtonText: "确认发布",
    cancelButtonText: "取消",
  });
}

async function handleStartUploadUnified() {
  if (productStore.targetPublishPlatform !== "douyin") {
    ElMessage.warning("请先切换到抖音账户并确认账户状态后再开始抖音发布");
    return;
  }
  if (shopAccountBusy.value) {
    ElMessage.warning("正在处理账户，请等账户状态确认后再发布");
    return;
  }
  if (isUploadMonitoring.value || isUploadStarting.value) {
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

  const snapshot = capturePublishSnapshot("douyin");
  if (!snapshot) return;
  isUploadStarting.value = true;
  try {
    // 提交模式可能在设置里被改过，每次上传前重新读，别用启动时的旧值发布。
    await loadPublishSubmitMode();
    const realPublish = publishSubmitMode.value === "publish";

    if (realPublish && !(await confirmRealPublish())) {
      return;
    }

    if (productStore.targetPublishPlatform !== "douyin") {
      ElMessage.error("当前账户平台未确认或已经变化，未启动抖音发布，请刷新账户状态后重试");
      return;
    }

    ensureUploadLoading("正在保存当前商品资料…");
    const savedRevision = await savePublishSnapshot(snapshot);
    if (!savedRevision) {
      closeUploadLoading();
      return;
    }
    ensureUploadLoading(realPublish ? "正在提交发布…" : "正在启动上传…");
    const response = await productStore.startUpload(
      snapshot.recordId,
      { ...(realPublish ? { confirmFinalPublish: true } : { stopBeforeSubmit: true }), accountProfile: snapshot.accountProfile, expectedRecordRevision: savedRevision }
    );
    if (!response.success) {
      closeUploadLoading();
      ElMessage.error(response.message || response.msg || "上传启动失败，后端未返回失败原因");
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
    const reason = axios.isAxiosError<ApiResponse>(error)
      ? error.response?.data?.message || error.response?.data?.msg || error.message
      : error instanceof Error ? error.message : String(error);
    ElMessage.error(`抖音发布启动失败：${reason}`);
  } finally {
    isUploadStarting.value = false;
  }
}

async function handlePublishByAccount() {
  if (publishButtonDisabled.value) return;
  if (productStore.targetPublishPlatform === "douyin") {
    await handleStartUploadUnified();
    return;
  }
  if (productStore.targetPublishPlatform !== "taobao") return;

  const recordId = productStore.currentProductId;
  const account = productStore.currentShopSession;
  const record = productStore.currentProduct;
  if (!recordId || record?.id !== recordId) {
    ElMessage.warning("请先选择并加载一个商品，再开始淘宝填写");
    return;
  }
  if (account?.platform !== "taobao" || !account.active_profile) {
    ElMessage.warning("请先选择淘宝账户");
    return;
  }
  const duplicateGroups = collectDuplicateSkuGroups(productStore.currentSkus);
  if (duplicateGroups.length > 0) {
    await showDuplicateSkuAlert("淘宝填写", duplicateGroups);
    return;
  }
  const title = formData.value.title.trim();
  const keyword = CATEGORY_OPTIONS.find((entry) => entry.value === formData.value.clazz)?.label;
  const stock = formData.value.repo;
  if (!title || !keyword || typeof stock !== "number" || !Number.isInteger(stock) || stock < 0) {
    ElMessage.warning("请填写商品标题、商品种类和有效的整数库存");
    return;
  }
  const skus = productStore.currentSkus;
  if (!skus.length || skus.some((sku) => !sku.name.trim() || typeof sku.price !== "number" || !Number.isFinite(sku.price) || sku.price <= 0)) {
    ElMessage.warning("请填写全部规格名称及大于 0 的有效售价");
    return;
  }

  // 商品种类仅作淘宝类目搜索词；销售规格使用完整名称，不拆分或猜测尺码。
  // 主单价兼作智能定价成本，不能作为淘宝售价；本次只使用每条 SKU 的已编辑价格。
  const snapshot = capturePublishSnapshot("taobao");
  if (!snapshot) return;
  const accountProfile = snapshot.accountProfile;
  let requestedAt = Date.now();
  const product: TaobaoProductRequest = {
    title,
    category_keyword: keyword,
    sku_mode: "custom",
    outer_id: record.name,
    skus: skus.map((sku) => ({
      spec_values: { "颜色分类": sku.name.trim() },
      price: sku.price as number, // 上方已逐条校验为正数；空价格不能进入请求。
      stock,
      ...(sku.path ? { image_path: sku.path } : {}),
    })),
  };
  isUploadStarting.value = true;
  try {
    ensureUploadLoading("正在保存当前商品资料…");
    const savedRevision = await savePublishSnapshot(snapshot);
    if (!savedRevision) {
      closeUploadLoading();
      return;
    }
    ensureUploadLoading("正在启动上传…");
    requestedAt = Date.now();
    const response = await productStore.startTaobaoFill(recordId, product, accountProfile, savedRevision);
    const data = response.data;
    if (!response.success) {
      closeUploadLoading();
      ElMessage.error(response.message || response.msg || "上传启动失败，后端未返回失败原因");
      return;
    }
    if (typeof data?.task_id !== "string" || !data.task_id.trim()) {
      throw new Error("后端已接受启动，但未返回淘宝任务编号");
    }
    // POST 已启动的真实任务必须继续跟进，不能因当前表单或账户变动而丢弃。
    startUploadMonitoring(data.task_id, "local", null, "taobao", { recordId, accountProfile });
    if (data.dry_run !== false || data.stop_before_submit !== true) {
      ElMessage.warning("后端返回的任务模式与提交前填写要求不一致，已接上进度，请核对任务状态");
    }
  } catch (error) {
    closeUploadLoading();
    const reason = axios.isAxiosError<ApiResponse>(error)
      ? error.response?.data?.message || error.response?.data?.msg || error.message
      : error instanceof Error ? error.message : String(error);
    const status = axios.isAxiosError(error) ? error.response?.status : undefined;
    const explicitlyRejected = axios.isAxiosError<ApiResponse>(error) && error.response?.data?.success === false;
    if (!explicitlyRejected && (!status || status >= 500 || status === 408)) {
      taobaoUnknownStart.value = { recordId, accountProfile, requestedAt };
      ElMessage.error(`淘宝填写启动结果未知：${reason}。将读取任务状态，请勿重复启动`);
    } else {
      ElMessage.error(`淘宝填写启动失败：${reason}`);
    }
    // 网络结果未知时，任务可能已创建；立即读取任务列表接回实际任务，不重发请求。
    await syncExternalUploadTask({ silent: true });
  } finally {
    isUploadStarting.value = false;
  }
}

function handleCancelSelect() {
  if (uploadBusy.value) return;
  selectedSkuPaths.value.clear();
  ElMessage.success("已取消选择");
}

// 清空全部
async function handleDeleteAll() {
  if (uploadBusy.value) return;
  const confirmed = await confirmAction(
    "确定清空所有产品吗？采集商品的本地文件夹及全部文件会移入回收站；手动导入的原始文件保留。列表中的编辑信息会删除。",
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
    ElMessage.error(`清空失败：${productStore.lastActionError || "未知原因"}`);
  }
}

// SKU选中切换
function handleSkuSelect(sku: SKU) {
  if (uploadBusy.value) return;
  if (selectedSkuPaths.value.has(sku.path)) {
    selectedSkuPaths.value.delete(sku.path);
  } else {
    selectedSkuPaths.value.add(sku.path);
  }
}

// SKU删除
async function handleSkuDelete(sku: SKU) {
  if (uploadBusy.value) return;
  const confirmed = await confirmAction("确定删除该SKU吗？", "提示", {
    type: "warning",
  });
  if (!confirmed) return;

  const success = await productStore.deleteSku(sku.path);
  if (success) {
    ElMessage.success("删除成功");
  } else {
    ElMessage.error(`删除失败：${productStore.lastActionError || "未知原因"}`);
  }
}

onMounted(() => {
  void loadPublishSubmitMode();
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
      <!-- 当前账户决定发布平台，平台仅在添加账户时选择。 -->
      <ShopStatusBar
        ref="shopStatusBarRef"
        :paused="uploadBusy"
        @changed="handleShopSessionChanged"
        @busy-change="shopAccountBusy = $event"
      />

      <!-- 链接采集区域 -->
      <CaptureSection @imported="productStore.fetchProducts()" />

      <!-- 产品列表 -->
      <div class="product-list">
        <h2 class="panel-title">本地商品目录</h2>

        <el-scrollbar class="product-scroll">
          <div
            v-for="product in productStore.products"
            :key="product.id"
            class="product-item"
            :class="{ active: product.id === productStore.currentProductId, 'selection-disabled': uploadBusy || productStore.detailLoading }"
            :aria-disabled="uploadBusy || productStore.detailLoading"
            :tabindex="uploadBusy || productStore.detailLoading ? -1 : 0"
            role="button"
            @click="handleProductClick(product.id)"
            @keydown.enter="handleProductClick(product.id)"
            @keydown.space.prevent="handleProductClick(product.id)"
            @keydown.shift.f10.prevent="handleProductMenuKey($event, product.id)"
            @keydown.context-menu.prevent="handleProductMenuKey($event, product.id)"
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
        {{ publishPlatformLabel ? `${publishPlatformLabel}发布 · ` : "商品配置 · " }}{{ productStore.currentProduct?.name || "请选择商品" }}
      </h1>

      <el-form label-position="top" class="product-form" :disabled="uploadBusy">
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
              <span class="step-name">{{ step.label || step.name }}</span>
              <span v-if="step.elapsed_ms != null" class="step-time">{{ step.elapsed_ms }}ms</span>
              <span v-if="step.summary" class="step-summary">{{ step.summary }}</span>
            </div>
          </div>
        </div>

        <!-- 底部按钮 -->
        <div class="action-buttons">
          <el-button type="primary" :loading="uploadBusy" :disabled="publishButtonDisabled" @click="handlePublishByAccount">
            {{ publishActionText }}
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
      <div v-if="taobaoUnknownStart || uploadMonitoringPaused" class="upload-task-actions">
        <span v-if="taobaoUnknownStart">淘宝填写启动结果待确认</span>
        <el-button @click="retryUploadProgress">重新读取进度</el-button>
        <el-button v-if="activeUploadTaskId" type="warning" :loading="uploadTaskCancelling" @click="cancelUploadTask">取消上传</el-button>
      </div>
    </div>

    <!-- 右键菜单 -->
    <ContextMenu
      v-model:visible="contextMenuVisible"
      :position="contextMenuPosition"
      @action="handleContextMenuAction"
    />
    <ProductMediaManager v-model="mediaManagerVisible" :record-id="mediaManagerProductId" :processing-disabled="uploadBusy" />

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
:global(.product-upload-loading .upload-loading-content .el-button) {
  margin-top: 16px;
}

.upload-task-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

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

  &.selection-disabled {
    cursor: wait;
  }

  &:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: -2px;
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
  min-width: 0;
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
