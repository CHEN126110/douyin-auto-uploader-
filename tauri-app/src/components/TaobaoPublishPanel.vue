<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import axios from "axios";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, tauriCommands } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import type {
  ApiResponse,
  TaobaoPacketExport,
  TaobaoPreparation,
  TaobaoPreparationCheck,
  TaobaoPublishPayload,
  TaobaoProductRequest,
  TaobaoPublishTask,
  TaobaoReadiness,
  TaobaoListingMode,
} from "@/types";

type TaobaoDraft = {
  title: string;
  guide_title: string;
  category_path: string;
  item_price: string;
  total_stock: string;
  freight_template_name: string;
  /** 商家编码。**选填**；流水线的 `fill_base` 支持它，以前界面没地方填。 */
  outer_id: string;
  /** 「属性名 → 属性值」。`fill_props` 用；例如 品牌='无品牌/无注册商标'。 */
  props: Array<{ prop_name: string; value_name: string }>;
  skus: Array<{
    index: number;
    name: string;
    /**
     * 规格值，写成 `尺码=M(37-41)`（多个用逗号分隔）。
     * **必须由操作人明确写出**——流水线不许从 SKU 名字里拆属性值（那是猜字段）。
     */
    spec_values: string;
    price: string;
    stock: string;
  }>;
};

const emit = defineEmits<{ (event: "busy-change", busy: boolean): void }>();
const props = defineProps<{
  accountBusy?: boolean;
  initialTitle?: string;
  initialRecordId?: number;
  initialAccountProfile?: string;
}>();
const productStore = useProductStore();
const selectedRecordId = computed(() => {
  const product = productStore.currentProduct;
  return product && product.id === productStore.currentProductId ? product.id : null;
});
const activeTaobaoAccount = computed(() =>
  productStore.currentShopSession?.platform === "taobao" ? productStore.currentShopSession : null
);
const contextMatches = computed(() =>
  (props.initialRecordId === undefined || props.initialRecordId === selectedRecordId.value) &&
  (props.initialAccountProfile === undefined || props.initialAccountProfile === activeTaobaoAccount.value?.active_profile)
);
const contextInvalidated = ref(false);

function emptyDraft(): TaobaoDraft {
  return {
    title: "",
    guide_title: "",
    category_path: "",
    item_price: "",
    total_stock: "",
    freight_template_name: "",
    outer_id: "",
    props: [],
    skus: [],
  };
}

const draft = ref<TaobaoDraft>(emptyDraft());
const report = ref<TaobaoPreparation | null>(null);
const packet = ref<TaobaoPacketExport | null>(null);
const readiness = ref<TaobaoReadiness | null>(null);
const readinessLoading = ref(false);
const readinessError = ref("");
const actionError = ref("");
const fieldErrors = ref<Record<string, string>>({});
const action = ref<"load" | "check" | "export" | null>(null);
const loadedRecordId = ref<number | null>(null);
const pendingRequests = ref(0);
const busy = computed(() => pendingRequests.value > 0);
let requestVersion = 0;
let readinessVersion = 0;
let draftRevision = 0;
let checkedRevision = -1;

const canExport = computed(() =>
  Boolean(
    readiness.value &&
    contextMatches.value &&
    !contextInvalidated.value &&
    report.value?.can_export &&
    report.value.record_id === selectedRecordId.value &&
    loadedRecordId.value === selectedRecordId.value &&
    checkedRevision === draftRevision &&
    !props.accountBusy &&
    !busy.value
  )
);

watch(busy, (value) => emit("busy-change", value), { flush: "sync" });
watch(draft, () => {
  draftRevision += 1;
  checkedRevision = -1;
  report.value = null;
  packet.value = null;
  actionError.value = "";
  fieldErrors.value = {};
}, { deep: true, flush: "sync" });

function errorMessage(error: unknown): string {
  if (axios.isAxiosError<ApiResponse>(error)) {
    return error.response?.data?.message || error.response?.data?.msg || error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

function responseData<T>(response: ApiResponse<T>, failure: string): T {
  if (!response.success || !response.data) {
    throw new Error(response.message || response.msg || failure);
  }
  return response.data;
}

async function loadReadiness() {
  const version = ++readinessVersion;
  readinessLoading.value = true;
  readinessError.value = "";
  readiness.value = null;
  try {
    const data = responseData(await api.getTaobaoReadiness(), "未能读取淘宝路线状态");
    if (version !== readinessVersion) return;
    // ⚠️ 这里原先还要求 `automatic_publish_ready === false`——那是**流水线尚未实现时**
    // 的不变量。现在后端如实报告，那个校验会让界面反过来报错。
    // 只保留「平台与模式对得上」这一条。
    if (data.platform !== "taobao" || data.mode !== "automated_pipeline") {
      throw new Error("淘宝路线状态与当前流水线模式不一致，请检查后端版本");
    }
    readiness.value = data;
  } catch (error) {
    if (version === readinessVersion) {
      readinessError.value = `读取淘宝路线状态失败：${errorMessage(error)}`;
    }
  } finally {
    if (version === readinessVersion) readinessLoading.value = false;
  }
}

function isCurrentRequest(version: number, recordId: number, revision?: number) {
  return version === requestVersion && contextMatches.value && !contextInvalidated.value &&
    activeTaobaoAccount.value !== null && selectedRecordId.value === recordId &&
    (revision === undefined || revision === draftRevision);
}

function beginAction(mode: "load" | "check" | "export") {
  pendingRequests.value += 1;
  action.value = mode;
}

function finishAction() {
  pendingRequests.value -= 1;
  if (pendingRequests.value === 0) action.value = null;
}

function invalidateBoundContext() {
  contextInvalidated.value = true;
  requestVersion += 1;
  loadedRecordId.value = null;
  draft.value = emptyDraft();
  report.value = null;
  packet.value = null;
  actionError.value = "当前商品或账户已变化，此次淘宝发布资料已失效。请等待进行中的请求结束后关闭窗口，再从主页面重新开始。";
}

function validatePreparation(data: TaobaoPreparation, recordId: number, accountProfile: string) {
  // ⚠️ 原先还要求 `automatic_publish_ready !== false`——那是流水线尚未实现时的不变量。
  // 现在后端如实报告，这个校验会让界面反过来把正常响应判成「不一致」。
  if (data.platform !== "taobao" || data.record_id !== recordId || data.account_profile !== accountProfile) {
    throw new Error("淘宝资料响应与当前账户或商品不一致，未应用返回结果");
  }
}

function seedDraft(data: TaobaoPreparation) {
  draft.value = {
    title: data.title,
    guide_title: data.guide_title,
    category_path: data.category_path,
    item_price: data.item_price === null ? "" : String(data.item_price),
    total_stock: data.total_stock === null ? "" : String(data.total_stock),
    freight_template_name: data.freight_template_name,
    // 商家编码**资料里没有**——它是界面新增的选填字段，初始就是空。
    outer_id: "",
    // 类目属性与规格值**不从资料里推断**：资料里没有这两样，
    // 由操作人自己填。空着就是空着——流水线会如实报阻塞项，不替人猜。
    props: [],
    skus: data.skus.map((sku) => ({
      index: sku.index,
      name: sku.name,
      spec_values: "",
      price: sku.price === null ? "" : String(sku.price),
      stock: sku.stock === null ? "" : String(sku.stock),
    })),
  };
}

async function loadProductPreparation() {
  if (!contextMatches.value || contextInvalidated.value) {
    invalidateBoundContext();
    return;
  }
  const version = ++requestVersion;
  const recordId = selectedRecordId.value;
  const accountProfile = activeTaobaoAccount.value?.active_profile;
  loadedRecordId.value = null;
  draft.value = emptyDraft();
  report.value = null;
  packet.value = null;
  if (!recordId || !accountProfile) {
    if (!busy.value) action.value = null;
    return;
  }
  beginAction("load");
  try {
    const data = responseData(
      await productStore.checkTaobaoPreparation({
        record_id: recordId,
        account_profile: accountProfile,
        ...(props.initialTitle !== undefined ? { overrides: { title: props.initialTitle } } : {}),
      }),
      "未能读取当前商品的淘宝资料"
    );
    if (!isCurrentRequest(version, recordId)) return;
    validatePreparation(data, recordId, accountProfile);
    seedDraft(data);
    loadedRecordId.value = recordId;
    report.value = data;
    checkedRevision = draftRevision;
  } catch (error) {
    if (isCurrentRequest(version, recordId)) {
      actionError.value = `读取淘宝资料失败：${errorMessage(error)}`;
    }
  } finally {
    finishAction();
  }
}

function parseNumber(value: string, field: string, label: string, integer: boolean): number | null {
  if (!value.trim()) return null;
  const number = Number(value);
  if (!Number.isFinite(number) || (integer ? !Number.isInteger(number) || number < 0 : number <= 0)) {
    fieldErrors.value[field] = integer ? `${label}需填写 0 或正整数` : `${label}需填写大于 0 的金额`;
    return null;
  }
  return number;
}

function buildPayload(): TaobaoPublishPayload | null {
  if (!contextMatches.value || contextInvalidated.value) return null;
  const recordId = selectedRecordId.value;
  const accountProfile = activeTaobaoAccount.value?.active_profile;
  if (!recordId || !accountProfile || loadedRecordId.value !== recordId) return null;
  fieldErrors.value = {};
  const overrides: NonNullable<TaobaoPublishPayload["overrides"]> = {
    title: draft.value.title,
    guide_title: draft.value.guide_title,
    category_path: draft.value.category_path,
    freight_template_name: draft.value.freight_template_name,
    item_price: parseNumber(draft.value.item_price, "item_price", "商品一口价", false),
    total_stock: parseNumber(draft.value.total_stock, "total_stock", "商品总库存", true),
    skus: draft.value.skus.map((sku) => ({
      index: sku.index,
      price: parseNumber(sku.price, `sku_price_${sku.index}`, `规格「${sku.name}」售价`, false),
      stock: parseNumber(sku.stock, `sku_stock_${sku.index}`, `规格「${sku.name}」库存`, true),
    })),
  };
  if (Object.keys(fieldErrors.value).length) {
    actionError.value = "价格或库存填写有误，请修正标出的字段后重新检查。";
    return null;
  }
  return { record_id: recordId, account_profile: accountProfile, overrides };
}

/**
 * 把界面上的 `draft` 组装成流水线要的 `product`。
 *
 * **只搬界面真的收集到的内容**，缺什么就留空——静态预检会把缺的报成阻塞项。
 * 这里绝不替用户编造属性值或规格值。
 */
function buildProductRequest(): TaobaoProductRequest | null {
  const specValuesOf = (raw: string): Record<string, string> => {
    const out: Record<string, string> = {};
    for (const piece of raw.split(",")) {
      const text = piece.trim();
      if (!text) continue;
      const at = text.indexOf("=");
      if (at <= 0) continue;
      const key = text.slice(0, at).trim();
      const value = text.slice(at + 1).trim();
      if (key && value) out[key] = value;
    }
    return out;
  };

  const props = draft.value.props
    .map((entry) => ({ prop_name: entry.prop_name.trim(), value_name: entry.value_name.trim() }))
    .filter((entry) => entry.prop_name && entry.value_name);

  // ⚠️ **必须走 `parseNumber`，不能写 `Number(x) || 0`。**
  //
  // ``Number(x) || 0`` 会把**空值和垃圾都变成 0**——那是「猜一个默认值让它跑通」，
  // 项目红线明确禁止。更糟的是 ``Number("1e999") === Infinity``，
  // 而 ``Infinity || 0`` 仍是 ``Infinity``，会一路写进表单。
  //
  // 这里与 `buildPayload` 用**同一套**校验：空 → 报错、非数字 → 报错、
  // 售价 <= 0 → 报错、库存非整数或 < 0 → 报错。有任何一处不对就**整个不发**，
  // 让操作人先把值改对。
  fieldErrors.value = {};
  const parsedSkus = draft.value.skus.map((sku) => ({
    index: sku.index,
    spec_values: specValuesOf(sku.spec_values),
    price: parseNumber(sku.price, `sku_price_${sku.index}`, `规格「${sku.name}」售价`, false),
    stock: parseNumber(sku.stock, `sku_stock_${sku.index}`, `规格「${sku.name}」库存`, true),
  }));
  if (Object.keys(fieldErrors.value).length) {
    actionError.value = "价格或库存填写有误，请修正标出的字段后再发起淘宝发布。";
    return null;
  }
  const skus = parsedSkus.map((sku) => ({
    spec_values: sku.spec_values,
    price: sku.price as number,
    stock: sku.stock as number,
  }));

  const product: TaobaoProductRequest = {};
  if (draft.value.title.trim()) product.title = draft.value.title.trim();
  // 导购标题是选填；以前它只发给「资料检查/资料包」，**不会进发布流水线**。
  if (draft.value.guide_title.trim()) product.guide_title = draft.value.guide_title.trim();
  if (draft.value.category_path.trim()) product.category_path = draft.value.category_path.trim();
  if (draft.value.freight_template_name.trim()) {
    product.freight_template_name = draft.value.freight_template_name.trim();
  }
  if (props.length) product.props = props;
    // 商家编码是**选填**：留空就不发，让流水线如实报「跳过」。
    const outerId = draft.value.outer_id.trim();
    if (outerId) product.outer_id = outerId;
  if (skus.length) product.skus = skus;
  return product;
}

async function checkPreparation() {
  if (busy.value || props.accountBusy || !contextMatches.value || contextInvalidated.value) return;
  const payload = buildPayload();
  if (!payload) return;
  const version = ++requestVersion;
  const revision = draftRevision;
  beginAction("check");
  report.value = null;
  packet.value = null;
  actionError.value = "";
  try {
    const data = responseData(await productStore.checkTaobaoPreparation(payload), "淘宝资料检查未执行完成");
    if (!isCurrentRequest(version, payload.record_id, revision)) return;
    validatePreparation(data, payload.record_id, payload.account_profile!);
    report.value = data;
    checkedRevision = revision;
    ElMessage.info(data.can_export ? "检查已完成，可生成本地淘宝资料包" : "检查已完成，请按报告补全资料");
  } catch (error) {
    if (isCurrentRequest(version, payload.record_id, revision)) {
      actionError.value = `淘宝资料检查失败：${errorMessage(error)}`;
    }
  } finally {
    finishAction();
  }
}

async function exportPacket() {
  if (!canExport.value) return;
  const payload = buildPayload();
  if (!payload) return;
  const version = ++requestVersion;
  const revision = draftRevision;
  beginAction("export");
  actionError.value = "";
  packet.value = null;
  try {
    const data = responseData(await productStore.exportTaobaoPacket(payload), "淘宝资料包未生成");
    if (!isCurrentRequest(version, payload.record_id, revision)) return;
    if (data.platform !== "taobao" || data.record_id !== payload.record_id || data.account_profile !== payload.account_profile || !data.packet_dir) {
      throw new Error("淘宝资料包响应与当前账户或商品不一致，未打开返回目录");
    }
    packet.value = data;
    ElMessage.success("本地淘宝资料包已生成，请在淘宝工作台人工核对并发布");
    await openPacketFolder();
  } catch (error) {
    if (isCurrentRequest(version, payload.record_id, revision)) {
      // 导出失败后必须重新检查，避免使用文件变化前的检查结果继续生成。
      report.value = null;
      checkedRevision = -1;
      actionError.value = `生成淘宝资料包失败：${errorMessage(error)}`;
    }
  } finally {
    finishAction();
  }
}

async function openPacketFolder() {
  if (!packet.value) return;
  try {
    await tauriCommands.openFolder(packet.value.packet_dir);
  } catch (error) {
    actionError.value = `资料包已生成，打开目录失败：${errorMessage(error)}。可按下方路径手动打开。`;
  }
}

function checkStatus(check: TaobaoPreparationCheck) {
  return { ok: "已具备", warning: "待核对", missing: "缺少资料" }[check.status];
}

function checkType(check: TaobaoPreparationCheck): "success" | "warning" | "danger" {
  return check.status === "ok" ? "success" : check.status === "warning" ? "warning" : "danger";
}

watch(
  [selectedRecordId, () => activeTaobaoAccount.value?.active_profile],
  () => { void loadProductPreparation(); },
  { immediate: true }
);
// ========== 淘宝发布流水线任务 ==========

/**
 * 本次任务走校对还是真实发布。
 *
 * **默认校对**——零写入默认的红线不动。真实发布需要三把锁同时打开：
 *
 * 1. 这里选「真实发布」；
 * 2. 每次启动都弹确认框（写明发到哪个店、提交后无法撤销）；
 * 3. Sidecar 侧的环境变量 `TAOBAO_UPLOAD_ALLOW_WRITE` 与
 *    `TAOBAO_UPLOAD_ALLOW_SUBMIT=1`。
 *
 * **只开前两把不会有任何写入**——真正的授权在服务端，不由界面决定。
 */
const publishMode = ref<"dry_run" | "real">("dry_run");
/**
 * 上架方式。**默认「放入仓库」，不是「立刻上架」。**
 *
 * 页面自己的默认值是「立刻上架」——最危险的那个恰好是默认值，所以这里刻意不跟随：
 * 填完先进仓库，人在卖家中心复核后再上架。要立刻上架必须**显式**选。
 */
const listingMode = ref<TaobaoListingMode>("放入仓库");
/**
 * 是否在回读通过后保存草稿。**默认 false。**
 *
 * 授权只是白名单，这个开关才决定点不点「保存草稿」按钮。默认不勾——
 * 否则每跑一次平台就多一条草稿（上限只有 10 条）。
 */
const saveDraft = ref(false);

/** 真实发布前的显式确认。与抖店的 `confirmRealPublish` 对应。 */
async function confirmRealPublish(): Promise<boolean> {
  const account = activeTaobaoAccount.value?.active_profile || "（读不到账户）";
  const shop = activeTaobaoAccount.value?.shop_name || "";
  const target = shop ? `${shop}（${account}）` : account;
  try {
    await ElMessageBox.confirm(
      `<div>将发布到：<b>${target}</b></div>` +
        "<div style=\"margin-top:8px\">商品提交后会直接上架，<b>无法撤销</b>。</div>" +
        "<div style=\"margin-top:8px;color:#9a5b00\">还要求 Sidecar 侧已开启写入与提交授权；" +
        "没开的话任务会在写操作前停下，不会写入平台。</div>",
      "确认真实发布",
      {
        type: "warning",
        dangerouslyUseHTMLString: true,
        confirmButtonText: "确认发布",
        cancelButtonText: "取消",
        confirmButtonClass: "el-button--danger",
      },
    );
    return true;
  } catch {
    return false;
  }
}
//
// 与抖店的 /api/upload/* 同一套交互：启动 → 轮询 status → 展示进度与阶段。
//
// ⚠️ **「流水线跑完」不等于「商品已上架」。** 后端返回的 publish_confirmed 恒为
// false（提交通道的成功特征尚未实证），所以界面上必须把这两件事分开说，
// 不能因为 status === "succeeded" 就显示「发布成功」。
const publishTask = ref<TaobaoPublishTask | null>(null);
const publishStarting = ref(false);
/** 正在请求取消。与 `publishStarting` 分开——两者可以同时为真。 */
const publishCancelling = ref(false);
const publishError = ref("");
const publishPollToken = ref(0);

const publishStatusText = computed(() => {
  const task = publishTask.value;
  if (!task) return "";
  if (task.status === "failed") return task.error || task.message || "流水线未通过";
  return task.message || "";
});

const publishRunning = computed(
  () => publishTask.value?.status === "pending" || publishTask.value?.status === "running"
);

function stopPublishPolling() {
  publishPollToken.value += 1;
}

async function pollPublish(taskId: string, token: number) {
  // 轮询到终态或组件卸载为止。用 token 而不是布尔标记，
  // 这样重启一个任务时旧循环会自己退出，不会两个循环同时写同一份状态。
  while (publishPollToken.value === token) {
    await new Promise((resolve) => window.setTimeout(resolve, 1500));
    if (publishPollToken.value !== token) return;
    try {
      const response = await api.getTaobaoPublishStatus(taskId);
      if (publishPollToken.value !== token) return;
      if (!response.success || !response.data) {
        throw new Error(response.message || response.msg || "后端未返回任务状态");
      }
      publishTask.value = response.data;
      if (!publishRunning.value) return;
    } catch (error) {
      if (publishPollToken.value !== token) return;
      // 轮询失败不当作任务失败——如实说「读不到进度」，保留上一次状态。
      publishError.value = `读取发布进度失败：${errorMessage(error)}`;
      return;
    }
  }
}

/**
 * 请求取消当前任务。
 *
 * **取消的语义要如实说**：接口只在**阶段边界**检查取消标记，
 * **不会打断正在执行的那一步**。所以提示写成「当前阶段结束后停止」，
 * 不能写成像「立刻停了」那样。
 */
async function cancelPublish() {
  const taskId = publishTask.value?.task_id;
  if (!taskId || publishCancelling.value) return;
  publishCancelling.value = true;
  publishError.value = "";
  try {
    const response = await api.cancelTaobaoPublish(taskId);
    if (!response.success) {
      throw new Error(response.message || response.msg || "后端未接受取消请求");
    }
    // 不在这里改 publishTask 的状态——**让轮询去读真实状态**，
    // 否则界面会显示一个后端并不知道的「已取消」。
    ElMessage.info("已请求取消，将在**当前阶段结束后**停止");
  } catch (error) {
    publishError.value = `取消失败：${errorMessage(error)}`;
  } finally {
    publishCancelling.value = false;
  }
}

async function startPublish() {
  const recordId = selectedRecordId.value;
  if (recordId === null || publishStarting.value || publishRunning.value) return;
  if (!contextMatches.value) {
    publishError.value = "当前商品或账户已变化，无法发起淘宝发布。";
    return;
  }
  // **必须带上 product**：不带的话流水线收不到标题/价格/库存/类目，
  // 会在静态预检报「标题为空」——这正是以前的样子。
  const product = buildProductRequest();
  if (!product) {
    // 校验没通过，`buildProductRequest` 已经写好了 fieldErrors 与 actionError。
    // **不发请求**——宁可让操作人改对，也不拿一个编出来的 0 去发布。
    return;
  }

  const realPublish = publishMode.value === "real";
  if (realPublish && !(await confirmRealPublish())) {
    // 操作人取消了确认——**一个字节都不发**。
    return;
  }

  publishStarting.value = true;
  publishError.value = "";
  stopPublishPolling();
  try {
    const response = await api.startTaobaoPublish(recordId, {
      // 真实发布：`dry_run=false` + `stop_before_submit=false`。
      // 但**Sidecar 侧的环境变量仍然拦着**——授权开关在服务端，不由界面决定。
      realPublish,
      product,
      // ⚠️ **必须带上账户标识。**
      //
      // Sidecar 的 `_require_publish_platform` 拿它做一致性校验：与当前账户
      // 不符时返回 `ACCOUNT_CHANGED`（「当前账户已改变，请刷新账户后重新检查
      // 发布资料」）。**没有它，那道检查就被完全跳过。**
      //
      // 后果很具体：为账户 A 准备的标题/价格/库存/类目，在切到账户 B 之后点发布
      // ——Sidecar 只检查「当前是淘宝账户」，**不检查是不是准备时的那个**，
      // 于是把为 A 准备的资料发到 B 上。
      //
      // 面板的 `contextMatches` 是**客户端**守卫；服务端这一道是纵深防御。
      // （`checkPreparation` 与 `exportPacket` 一直都带着它，只有这里漏了。）
      accountProfile: activeTaobaoAccount.value?.active_profile,
      // 上架方式与保存草稿：**必须显式带上**，否则界面上的选择到不了流水线
      // （实测踩过：不传时「上架方式」静默用默认值、保存草稿永远 skipped）。
      listingMode: listingMode.value,
      saveDraft: saveDraft.value,
    });
    const data = responseData(response, "未能启动淘宝发布");
    const token = publishPollToken.value;
    publishTask.value = {
      task_id: data.task_id,
      platform: "taobao",
      account_profile: activeTaobaoAccount.value?.active_profile || "",
      record_id: recordId,
      record_name: productStore.currentProduct?.name || "",
      status: "pending",
      progress: 0,
      message: "任务已创建",
      steps: [],
      dry_run: data.dry_run,
      stop_before_submit: data.stop_before_submit,
      publish_confirmed: false,
      created_at: new Date().toISOString(),
    };
    ElMessage.info(
      realPublish
        ? "已启动淘宝发布任务（真实写入；若 Sidecar 未授权会在写操作前停下）"
        : "已启动淘宝校对任务（dry-run，不会写入平台）"
    );
    void pollPublish(data.task_id, token);
  } catch (error) {
    publishError.value = `启动淘宝发布失败：${errorMessage(error)}`;
  } finally {
    publishStarting.value = false;
  }
}

/**
 * 接回**正在运行**的淘宝发布任务。
 *
 * ⚠️ **没有这一步，任务跑起来之后关掉面板再打开就看不到它了**——
 * 而它在 Sidecar 里继续跑。在「真实发布」模式下这尤其严重：
 * 任务正在往平台写，而用户既看不见进度、也点不到取消。
 *
 * `onBeforeUnmount` 会 `stopPublishPolling()`，所以轮询也一并恢复。
 *
 * **两条限制**：
 * * 只接**当前商品**的——否则会把别的商品的任务显示在这里；
 * * 只接 `pending` / `running` 的——已经结束的没有接的意义。
 */
async function restoreRunningTask() {
  if (publishTask.value) return;               // 已经有任务在跟了
  const recordId = selectedRecordId.value;
  if (recordId === null) return;
  try {
    const response = await api.listTaobaoPublishTasks();
    const data = response.data;
    if (!response.success || !data) return;
    const mine = (data.tasks || []).filter(
      (task) =>
        task.record_id === recordId &&
        (task.status === "pending" || task.status === "running"),
    );
    if (!mine.length) return;
    const task = mine[0];
    publishTask.value = task;
    const token = ++publishPollToken.value;
    void pollPublish(task.task_id, token);
    ElMessage.info("已接上正在运行的淘宝发布任务");
  } catch {
    // 接不回来不该打断面板——**但也不能假装接上了**，所以什么都不改。
  }
}

onMounted(() => {
  void loadReadiness();
  void restoreRunningTask();
});
onBeforeUnmount(() => {
  requestVersion += 1;
  readinessVersion += 1;
  stopPublishPolling();
  emit("busy-change", false);
});
</script>

<template>
  <section class="taobao-publish-panel" aria-labelledby="taobao-panel-title">
    <div class="panel-heading">
      <h1 id="taobao-panel-title">淘宝发布</h1>
      <el-tag type="warning" effect="plain">人工发布路线</el-tag>
    </div>
    <el-alert
      title="流水线默认校对模式；真实写入需服务端授权"
      description="下方「淘宝发布流水线」会驱动已登录的淘宝工作台。默认走校对模式（dry-run，不写平台）；「真实发布」需要三把锁同时打开：选真实发布 + 每次弹窗确认 + Sidecar 侧的环境变量授权。无论哪一步成功，是否上架都要在卖家中心人工核对。"
      type="info"
      :closable="false"
      show-icon
    />

    <div v-if="readinessError" class="error-section" role="alert">
      <el-alert :title="readinessError" type="error" :closable="false" show-icon />
      <el-button :loading="readinessLoading" @click="loadReadiness">重新读取路线状态</el-button>
    </div>

    <el-alert
      v-if="contextInvalidated"
      title="当前商品或账户已变化，此次淘宝发布资料已失效"
      :description="busy ? '进行中的请求仍在完成，请等待结束后关闭窗口，再从主页面重新开始。' : '请关闭窗口，从主页面确认当前商品与账户后重新开始。'"
      type="error"
      :closable="false"
      show-icon
    />

    <el-empty v-if="!selectedRecordId" description="从左侧选择一个本地商品，开始准备淘宝发布资料" />
    <el-scrollbar v-else class="preparation-scroll">
      <div class="preparation-content" :aria-busy="busy">
        <p class="product-name">当前商品：{{ productStore.currentProduct?.name }}</p>
        <p class="field-hint">当前淘宝账户：{{ activeTaobaoAccount?.active_profile_label }}（未验证登录）。请在淘宝工作台人工核对目标店铺。</p>
        <p class="field-hint">此处字段独立用于本次淘宝资料包。更换商品或账户后需重新填写，抖音商品配置不受影响。</p>

        <div v-if="actionError && !contextInvalidated" class="error-section" role="alert">
          <el-alert :title="actionError" type="error" :closable="false" show-icon />
          <el-button v-if="!contextInvalidated && loadedRecordId !== selectedRecordId" :loading="busy" @click="loadProductPreparation">
            重新读取商品资料
          </el-button>
        </div>
        <p v-if="action === 'load'" class="loading-text" role="status">正在读取本地商品与图片资料…</p>

        <el-form label-position="top" :disabled="busy || accountBusy || contextInvalidated || !contextMatches || loadedRecordId !== selectedRecordId">
          <el-form-item label="宝贝标题" required>
            <el-input v-model="draft.title" placeholder="填写淘宝宝贝标题" />
            <p class="field-hint">归档页面限制为 30 汉字 / 60 字符，检查时按淘宝字符规则核对。</p>
          </el-form-item>
          <el-form-item label="导购标题（选填）">
            <el-input v-model="draft.guide_title" placeholder="独立填写导购标题" />
            <p class="field-hint">归档页面限制为 15 汉字 / 30 字符。</p>
          </el-form-item>
          <el-form-item label="淘宝类目路径">
            <el-input v-model="draft.category_path" placeholder="填写在淘宝工作台核对过的完整类目路径" />
            <p class="field-hint">淘宝类目需人工核对，不复用抖音类目编号。</p>
          </el-form-item>
          <div class="two-column-fields">
            <el-form-item label="商品一口价（元）" :error="fieldErrors.item_price">
              <el-input v-model="draft.item_price" inputmode="decimal" placeholder="待确认，可留空" />
            </el-form-item>
            <el-form-item label="商品总库存" :error="fieldErrors.total_stock">
              <el-input v-model="draft.total_stock" inputmode="numeric" placeholder="待确认，可留空" />
            </el-form-item>
          </div>
          <p class="field-hint stock-hint">一口价与总库存需单独确认。空白会标记为待补，不自动计算或预填库存。</p>
          <el-form-item label="淘宝运费模板名称">
            <el-input v-model="draft.freight_template_name" placeholder="填写目标淘宝店铺中核对过的模板名称" />
          </el-form-item>
          <el-form-item label="商家编码">
            <el-input v-model="draft.outer_id" placeholder="选填；留空时流水线会如实报「跳过」" />
          </el-form-item>

          <h2 class="section-title">类目属性</h2>
          <p class="field-hint">
            流水线会按这里给出的「属性名 → 属性值」去填写并回读校验。属性值必须与平台候选<strong>完全一致</strong>；
            没有把握就留空——流水线会如实报阻塞项，不会替你猜。
          </p>
          <el-alert
            class="brand-hint"
            type="warning"
            :closable="false"
            show-icon
            title="多数类目要求先选品牌，否则「确认，下一步」始终不可点"
            description="未指定品牌时默认选择「无品牌」，也支持平台标准候选「无品牌/无注册商标」。指定品牌会按原值精确匹配；选项不可用或选择后「确认，下一步」仍不可点时停止，不会替你猜其他品牌。"
          />
          <div v-if="draft.props.length" class="sku-table-wrapper">
            <el-table :data="draft.props" border size="small" class="sku-table" row-key="prop_name">
              <el-table-column label="属性名" min-width="150">
                <template #default="{ row }">
                  <el-input v-model="row.prop_name" :aria-label="`属性名`" placeholder="例如 品牌" />
                </template>
              </el-table-column>
              <el-table-column label="属性值" min-width="220">
                <template #default="{ row }">
                  <el-input v-model="row.value_name" :aria-label="`属性值`" placeholder="例如 无品牌/无注册商标" />
                </template>
              </el-table-column>
              <el-table-column width="90">
                <template #default="{ $index }">
                  <el-button link type="danger" @click="draft.props.splice($index, 1)">移除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <el-button class="add-row-button" @click="draft.props.push({ prop_name: '', value_name: '' })">
            添加类目属性
          </el-button>

          <h2 class="section-title">规格售价与库存</h2>
          <p class="field-hint">规格名称与图片取自本地商品；淘宝售价与库存独立填写，未确认可留空。</p>
          <div v-if="draft.skus.length" class="sku-table-wrapper">
            <el-table :data="draft.skus" border size="small" class="sku-table" row-key="index">
              <el-table-column prop="name" label="规格名称" min-width="150" />
              <el-table-column label="规格值（属性名=属性值）" min-width="230">
                <template #default="{ row }">
                  <el-input
                    v-model="row.spec_values"
                    :aria-label="`${row.name}的规格值`"
                    placeholder="例如 尺码=M(37-41)"
                  />
                </template>
              </el-table-column>
              <el-table-column label="淘宝售价（元）" min-width="190">
                <template #default="{ row }">
                  <el-form-item :error="fieldErrors[`sku_price_${row.index}`]" class="sku-field">
                    <el-input v-model="row.price" :aria-label="`${row.name}的淘宝售价`" inputmode="decimal" placeholder="待确认" />
                  </el-form-item>
                </template>
              </el-table-column>
              <el-table-column label="淘宝库存" min-width="190">
                <template #default="{ row }">
                  <el-form-item :error="fieldErrors[`sku_stock_${row.index}`]" class="sku-field">
                    <el-input v-model="row.stock" :aria-label="`${row.name}的淘宝库存`" inputmode="numeric" placeholder="待确认" />
                  </el-form-item>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <p v-else class="field-hint">当前商品没有规格资料，请先核对本地商品目录。</p>
        </el-form>

        <div class="preparation-actions">
          <el-button
            :loading="action === 'check'"
            :disabled="busy || accountBusy || contextInvalidated || !contextMatches || !readiness || loadedRecordId !== selectedRecordId"
            @click="checkPreparation"
          >检查淘宝资料</el-button>
          <el-button type="primary" :loading="action === 'export'" :disabled="!canExport" @click="exportPacket">
            生成淘宝资料包
          </el-button>
          <span v-if="readinessLoading" class="field-hint" role="status">正在确认路线状态…</span>
          <span v-else-if="!report && !busy" class="field-hint">修改资料后，请重新检查再生成资料包。</span>
        </div>

        <div v-if="report" class="report-section" aria-live="polite">
          <h2 class="section-title">本地资料检查结果</h2>
          <div class="asset-summary">
            <el-tag effect="plain">主图 {{ report.assets.main.length }} 张</el-tag>
            <el-tag effect="plain">详情图 {{ report.assets.detail.length }} 张</el-tag>
            <el-tag effect="plain">规格图 {{ report.assets.sku.length }} 张</el-tag>
            <el-tag effect="plain">白底图 {{ report.assets.white_bg ? 1 : 0 }} 张</el-tag>
          </div>
          <el-table :data="report.checks" size="small" border class="checks-table">
            <el-table-column prop="label" label="检查项" min-width="110" />
            <el-table-column label="状态" width="108">
              <template #default="{ row }">
                <el-tag :type="checkType(row)" size="small">{{ checkStatus(row) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="说明与待办" min-width="240" />
          </el-table>
          <p class="field-hint">检查结果仅说明本地资料情况。即使允许导出，仍需在淘宝人工补全待办、核对店铺与表单后再发布。</p>
        </div>

        <div v-if="packet" class="packet-result" role="status">
          <h2 class="section-title">本地淘宝资料包已生成</h2>
          <p>{{ packet.message }}</p>
          <p>共 {{ packet.files_count }} 个文件，目录：<span class="packet-path">{{ packet.packet_dir }}</span></p>
          <el-button :disabled="busy" @click="openPacketFolder">打开资料包目录</el-button>
          <p class="field-hint">接下来请人工进入淘宝工作台核对并发布。本应用尚未执行淘宝上传、保存草稿或提交。</p>
        </div>

        <div class="pipeline-section" aria-live="polite">
          <h2 class="section-title">淘宝发布流水线</h2>
          <el-radio-group
            v-model="publishMode"
            :disabled="busy || publishRunning"
            size="small"
            class="publish-mode"
          >
            <el-radio-button value="dry_run">校对模式（不写平台）</el-radio-button>
            <el-radio-button value="real">真实发布</el-radio-button>
          </el-radio-group>
          <p v-if="publishMode === 'dry_run'" class="field-hint">
            流水线会自动走到淘宝发布工作台，按阶段核对并填写。
            <strong>校对模式（dry-run）</strong>：所有会写入平台的阶段都会被跳过，只会报告缺什么。
          </p>
          <p v-else class="field-hint publish-mode-warning">
            <strong>真实发布</strong>：流水线会真的上传图片、保存草稿，并走到提交。
            每次启动都会先弹确认框。<strong>还要求 Sidecar 侧已开启写入与提交授权</strong>
            （<code>TAOBAO_UPLOAD_ALLOW_WRITE</code> / <code>TAOBAO_UPLOAD_ALLOW_SUBMIT=1</code>）；
            没开的话任务会在写操作前停下，不会写入平台。
          </p>

          <!--
            ⚠️ **上架方式**：页面自己的默认值是「立刻上架」——最危险的那个恰好是默认值。
            所以这里默认选中「放入仓库」：填完先进仓库，人在卖家中心复核后再上架。
            要立刻上架必须**显式**选，不是一个疏忽就能让商品上架。
          -->
          <div v-if="publishMode === 'real'" class="listing-options">
            <div class="listing-row">
              <span class="listing-label">上架方式</span>
              <el-radio-group
                v-model="listingMode"
                :disabled="busy || publishRunning"
                size="small"
              >
                <el-radio-button value="放入仓库">放入仓库（推荐）</el-radio-button>
                <el-radio-button value="定时上架">定时上架</el-radio-button>
                <el-radio-button value="立刻上架">立刻上架</el-radio-button>
              </el-radio-group>
            </div>
            <p class="field-hint">
              默认<strong>放入仓库</strong>：商品先进仓库，不会立刻对消费者可见，复核后再上架。
            </p>
            <div class="listing-row">
              <el-checkbox v-model="saveDraft" :disabled="busy || publishRunning">
                填写完成后保存草稿
              </el-checkbox>
            </div>
            <p class="field-hint">
              勾选后，回读核对通过会在平台上存一条草稿（草稿箱上限 10 条）。
              不勾选则<strong>一个动作都不做</strong>——省得平台上堆测试草稿。
            </p>
          </div>
          <div class="preparation-actions">
            <el-button
              :type="publishMode === 'real' ? 'danger' : 'primary'"
              :loading="publishStarting"
              :disabled="busy || accountBusy || contextInvalidated || !contextMatches || selectedRecordId === null || publishRunning"
              @click="startPublish"
            >{{ publishMode === 'real' ? '真实发布（会写入平台）' : '开始校对（dry-run）' }}</el-button>
            <span v-if="publishRunning" class="field-hint" role="status">流水线运行中…</span>
            <!--
              ⚠️ **取消能力在 `api.ts` 里一直存在，但从来没被调用过**——
              任务跑起来就没有刹车（阶段可以各跑 20 秒）。
              「真实发布」模式下这是真实的可用性缺口。
            -->
            <el-button
              v-if="publishRunning"
              :loading="publishCancelling"
              @click="cancelPublish"
            >取消任务</el-button>
          </div>
          <p v-if="publishError" class="pipeline-error">{{ publishError }}</p>

          <div v-if="publishTask" class="pipeline-task">
            <div class="pipeline-status">
              <span class="status-text">{{ publishStatusText }}</span>
              <span class="status-pct">{{ publishTask.progress }}%</span>
            </div>
            <div class="status-progress-bar">
              <div class="status-progress-inner" :style="{ width: `${publishTask.progress}%` }" />
            </div>
            <p class="field-hint">
              任务 {{ publishTask.task_id }}　{{ publishTask.dry_run ? "校对模式" : "写入模式" }}　
              {{ publishTask.stop_before_submit ? "提交前截停" : "允许提交" }}
            </p>

            <el-table v-if="publishTask.steps.length" :data="publishTask.steps" size="small" border class="checks-table">
              <el-table-column prop="name" label="阶段" min-width="120" />
              <el-table-column prop="status" label="状态" width="90" />
              <el-table-column prop="summary" label="说明" min-width="240" />
            </el-table>

            <div v-if="publishTask.blockers && publishTask.blockers.length" class="pipeline-blockers">
              <h3 class="section-title">阻塞项 {{ publishTask.blockers.length }} 条</h3>
              <el-table :data="publishTask.blockers" size="small" border class="checks-table">
                <el-table-column prop="code" label="代码" width="180" />
                <el-table-column prop="field" label="位置" width="140" />
                <el-table-column prop="detail" label="说明" min-width="260" />
              </el-table>
            </div>

            <!-- 这一句是刻意写死的：流水线成功 ≠ 商品已上架。 -->
            <el-alert
              v-if="publishTask.status === 'succeeded'"
              title="流水线已完成，但商品是否上架尚未确认"
              description="提交通道的成功特征尚未实证，本应用不会声明发布成功。请到淘宝卖家中心核对商品是否出现在「出售中」或「仓库中」。"
              type="warning"
              :closable="false"
              show-icon
            />
          </div>
        </div>
      </div>
    </el-scrollbar>
  </section>
</template>

<style scoped>
.taobao-publish-panel {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  gap: 16px;
  color: var(--text-primary);
}

.panel-heading,
.asset-summary,
.preparation-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
}

.panel-heading h1 {
  margin: 0;
  font-size: var(--font-size-title);
}

.preparation-scroll {
  flex: 1;
  min-height: 0;
}

.preparation-content {
  padding: 0 12px 24px 0;
}

.product-name {
  margin: 0 0 8px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.field-hint,
.loading-text {
  margin: 6px 0 12px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.two-column-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.stock-hint {
  margin-top: -8px;
}

.publish-mode-warning {
  color: #b88230;
}

.brand-hint {
  margin: 0 0 12px;
}

.publish-mode {
  margin: 0 0 8px;
}

.section-title {
  margin: 20px 0 10px;
  font-size: 16px;
  font-weight: 600;
}

.sku-table-wrapper,
.checks-table {
  width: 100%;
}

/* 发布流水线的进度区。样式与 ProductManager 里的上传进度保持一致，
   两个平台的观感才对得上。 */
.pipeline-section {
  margin-top: 24px;
}

.pipeline-task {
  margin-top: 12px;
}

.pipeline-status {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.status-text {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary);
}

.status-pct {
  font-size: 12px;
  color: var(--text-secondary);
}

.status-progress-bar {
  height: 4px;
  background: #e4e7ed;
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 8px;
}

.status-progress-inner {
  height: 100%;
  background: #5c7cfa;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.pipeline-error {
  margin-top: 8px;
  color: #f56c6c;
  font-size: 13px;
}

.pipeline-blockers {
  margin-top: 12px;
}

.sku-field {
  margin: 8px 0 18px;
}

.preparation-actions {
  margin-top: 20px;
}

.preparation-actions .field-hint {
  margin: 0;
}

.asset-summary {
  margin-bottom: 12px;
}

.error-section {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 16px;
}

.error-section :deep(.el-alert) {
  width: 100%;
}

.packet-result {
  margin-top: 20px;
  padding: 16px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--radius-md);
  background: var(--el-fill-color-light);
  line-height: 1.6;
}

.packet-result .section-title {
  margin-top: 0;
}

.packet-path {
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .two-column-fields {
    grid-template-columns: minmax(0, 1fr);
    gap: 0;
  }
}
</style>
