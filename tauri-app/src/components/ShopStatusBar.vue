<script setup lang="ts">
/**
 * 账户切换器：添加时绑定平台，当前账户决定发布路线。
 * 两个平台的登录状态都由发布浏览器实测；平台差异（抖店读店铺 id + 店铺名，
 * 淘宝读账户 id + 会员名）收在后端 shop_session 里按平台分派。
 * 切换、添加、刷新收在原有下拉菜单中。
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import axios from "axios";
import { ElMessage, ElMessageBox } from "element-plus";
import { ArrowDown, Check, Close, Plus, Refresh } from "@element-plus/icons-vue";
import { api } from "@/services/api";
import type { ApiResponse, ShopProfile, ShopSessionState, ShopSwitchResult, TargetPublishPlatform } from "@/types";

const session = ref<ShopSessionState | null>(null);
// 首次查询完成前显示「检查中」，之后即使失败也不能一直停在这句，
// 否则用户会以为程序还在忙，其实是读不到。
const checked = ref(false);
const profiles = ref<ShopProfile[]>([]);
const loading = ref(false);
const switching = ref(false);
const sessionError = ref("");
const profileError = ref("");
const addDialogVisible = ref(false);
const accountDraft = ref<{ platform: TargetPublishPlatform; label: string }>({ platform: "douyin", label: "" });
/**
 * 待跟进的账户动作。只在「后端结果不完整」时存在：
 *
 * - ``awaiting_login``  后端已确认账户已登记并选中，只是用户还没登录。这不是错误，
 *   也不该挡住发布按钮——按抖店后台的逻辑，登录本身就是确认。
 * - ``unverified``      连后端确认都没拿到（网络中断、结果未知），不能据此重发请求，
 *   所以留着它后台重试，直到读到事实为止。
 */
type PendingAccountAction = {
  kind: "add" | "switch";
  platform: TargetPublishPlatform;
  label: string;
  profileName: string | null;
  phase: "awaiting_login" | "unverified";
  /**
   * 为什么停在 awaiting_login：
   * - ``login``  账户本身没问题，只是用户还没完成登录——继续添加账户是允许的；
   * - ``verify`` 连「当前选中哪家店」都还没读到，这时绝不能再叠一次账户操作。
   */
  stage: "login" | "verify" | null;
  confirmed: boolean;
  browserError: string | null;
  browserOpened: boolean;
};
const pendingAccountAction = ref<PendingAccountAction | null>(null);
const pendingFeedback = ref("");
let sessionQueryVersion = 0;
let profileQueryVersion = 0;
let loginWatchVersion = 0;
let accountActionVersion = 0;
let componentActive = true;

// 平时状态变化不频繁，15 秒一次够用。
const REFRESH_INTERVAL_MS = 15000;
// 刚打开登录页的这段时间要盯紧一点，用户登录完希望马上看到店铺名。
const LOGIN_WATCH_INTERVAL_MS = 3000;
// 加长到 5 分钟：扫码、短信验证、切换账号都可能超过 3 分钟，
// 盯丢之后用户会以为「登录了但没反应」。
const LOGIN_WATCH_DURATION_MS = 300000;
const DEFAULT_LOGIN_WATCH_MS = LOGIN_WATCH_DURATION_MS;
let refreshTimer: number | null = null;
let loginWatchTimer: number | null = null;

const emit = defineEmits<{
  (e: "changed", payload: ShopSessionState | null): void;
  (e: "busy-change", busy: boolean): void;
}>();

// 发布进行中时暂停轮询。查店铺状态要在抖店页面里执行一段 JS，
// 而那个页面这会儿正被发布流程自动填表，能不碰就不碰。
const props = defineProps<{ paused?: boolean }>();
const busy = computed(() => loading.value || switching.value);
const actionBusy = computed(() => Boolean(props.paused || switching.value));
// 周期状态查询只阻止发起发布，不应关闭正在使用的账户菜单或打断弹窗输入。
const accountActionsDisabled = computed(() => actionBusy.value || !checked.value);

watch(busy, (value) => emit("busy-change", value), { flush: "sync" });

function platformName(platform: TargetPublishPlatform) {
  return platform === "douyin" ? "抖音" : "淘宝";
}

function isValidProfileName(value: unknown): value is string {
  // 只检查返回标识的合法性，不在前端重新生成或改写账户编号。
  return typeof value === "string" && /^[A-Za-z0-9_.-]+$/.test(value) && !/^\.+$/.test(value);
}

function isCurrentAccountAction(version: number) {
  return componentActive && version === accountActionVersion;
}

function actionError(error: unknown): string {
  if (axios.isAxiosError<ApiResponse>(error)) {
    return error.response?.data?.message || error.response?.data?.msg || error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

const statusText = computed(() => {
  const pending = pendingAccountAction.value;
  const state = session.value;
  if (switching.value) return "正在处理账户…";
  // 刚添加/切换完还在登录，这行字就是用户此刻唯一需要知道的事。
  if (pending?.phase === "awaiting_login") return "等待登录…";
  if (!state) return checked.value ? "读不到账户状态" : "检查账户…";
  switch (state.status) {
    case "logged_in":
      return state.shop_name || (state.platform === "taobao" ? `淘宝账户 ${state.shop_id}` : `店铺 ${state.shop_id}`);
    case "logged_out":
    case "no_fxg_tab":
    case "no_taobao_tab":
    case "no_browser":
      return `${state.active_profile_label} · 未登录`;
    case "conflict":
      return "登录状态异常";
    default:
      return "读不到登录状态";
  }
});

const statusKind = computed(() => {
  const state = session.value;
  if (!state) return checked.value ? "warn" : "pending";
  if (state.status === "logged_in") return "ok";
  if (state.status === "conflict") return "error";
  return "warn";
});

/** 鼠标悬停时的补充说明。不占版面，也不需要额外角标。 */
const hintText = computed(() => {
  const pending = pendingAccountAction.value;
  const state = session.value;
  if (props.paused) return "当前操作进行中，完成后可切换或添加账户";
  if (pending?.phase === "awaiting_login") {
    return pending.stage === "verify"
      ? "后端已确认账户已选中，但本地还没读到当前实际情况，正在后台重试；点「重试确认」可立即读取。"
      : "已在浏览器中打开登录页，登录成功会自动显示店铺名，无需手动确认；点账户名可重新打开登录页。";
  }
  if (pending) {
    return "本次账户操作的结果还没读到，正在后台重试；点「重试确认」可立即读取当前账户与列表。";
  }
  if (!state) return sessionError.value;
  if (state.status === "logged_in") {
    return state.platform === "taobao" ? taobaoIdentityNote(state) : state.shop_id ? `店铺 ID ${state.shop_id}` : "";
  }
  if (["no_browser", "logged_out", "no_fxg_tab", "no_taobao_tab"].includes(state.status)) {
    return `打开账户菜单并选择${state.platform === "taobao" ? "淘宝" : "抖音"}账户，即可打开登录页；登录成功后自动确认，不用再点一次。`;
  }
  return state.error || "";
});

/**
 * 淘宝身份读到了之后，必须说清楚「读到的是什么」。
 *
 * 淘宝有三个**不同**的东西，混起来就会误判「验证的是哪家店」：
 *
 *   - **店铺名**（`shop_name`）：来自店铺信息接口的 `shopName`；
 *   - **店铺 ID**（`shop_id`）：来自同一接口的 `shopId`；
 *   - **账户 ID**（`account_id`）：来自 cookie `unb`，是「谁登录的」。
 *
 * 实测这两者形态不同（账户 13 位、店铺 9 位），不是同一个东西。
 * 只读到账户、没读到店铺时，如实说明缺的是哪一半。
 */
function taobaoIdentityNote(state: ShopSessionState) {
  const parts: string[] = [];
  if (state.shop_name) parts.push(`店铺「${state.shop_name}」`);
  if (state.shop_id) parts.push(`店铺 ID ${state.shop_id}`);
  if (state.account_id) parts.push(`账户 ID ${state.account_id}`);
  if (state.nick) parts.push(`会员名 ${state.nick}`);
  if (!state.shop_id) parts.push("尚未读到店铺身份，只确认了登录的账户");
  return parts.join(" · ");
}

/** 登录后可进入对应平台的任务，淘宝填写固定在提交前停止。 */
const loginPurpose = computed(() =>
  (pendingAccountAction.value?.platform || accountDraft.value.platform) === "taobao"
    ? "可以直接开始淘宝填写，填完后停在提交前"
    : "可以直接开始发布"
);

/** 添加淘宝账户时弹窗里的说明。 */
const taobaoNote = computed(() => {
  const parts = [
    "登录完成后会自动读取淘宝店铺身份（店铺名、店铺 ID）与账户身份（账户 ID、会员名），并按 profile 记录。",
  ];
  // 注意别把局部变量命名为 session —— 会遮蔽外层同名 ref，造成自引用。
  const current = session.value;
  if (current?.platform === "taobao" && current.status === "logged_in") {
    parts.push(`当前已读到：${taobaoIdentityNote(current)}。`);
  }
  parts.push("运费模板：淘宝侧的接口尚未实证，暂时读不到，会如实提示而不是显示空列表。");
  return parts.join("");
});

async function refresh(silent = true, force = false) {
  if (!componentActive) return null;
  if (loading.value) return null;
  // 发布进行中不主动去读页面，但登录轮询期间每一次都要问——
  // 用户刚扫码成功那几秒，正是这里最需要读到的时候。
  const loginWatching = loginWatchTimer !== null;
  if (props.paused && !force && !loginWatching) return null;
  if ((switching.value || pendingAccountAction.value) && !force && !loginWatching) return null;
  const version = ++sessionQueryVersion;
  loading.value = true;
  try {
    const response = await api.getShopSession(silent);
    if (version !== sessionQueryVersion) return null;
    const state = response.data;
    if (!response.success || !state) {
      throw new Error(response.message || response.msg || "后端未返回账户状态");
    }
    if (state.platform !== "douyin" && state.platform !== "taobao" && state.platform !== "xiaohongshu") {
      throw new Error("账户平台未确认，请检查后端版本后刷新账户状态");
    }
    if (!isValidProfileName(state.active_profile)) {
      throw new Error("当前账户编号未确认，请刷新账户状态");
    }
    session.value = state;
    sessionError.value = "";
    emit("changed", session.value);
    return state;
  } catch (error) {
    if (version !== sessionQueryVersion) return null;
    // 后端刚刚确认过的账户不能被一次读失败清空：清空会让发布按钮跟着消失，
    // 用户看到的是「账户没了」。这里只如实记下读失败，事实以最近一次读到为准。
    const confirmedProfile = pendingAccountAction.value?.confirmed
      ? pendingAccountAction.value.profileName
      : null;
    if (session.value?.active_profile !== confirmedProfile) {
      session.value = null;
      emit("changed", null);
    }
    sessionError.value = actionError(error);
    if (!silent) ElMessage.error(`读取账户状态失败：${sessionError.value}`);
    return null;
  } finally {
    if (version === sessionQueryVersion) {
      loading.value = false;
      checked.value = true;
    }
  }
}

function stopLoginWatch() {
  loginWatchVersion += 1;
  if (loginWatchTimer !== null) {
    window.clearInterval(loginWatchTimer);
    loginWatchTimer = null;
  }
}

function retirePendingSessionQuery() {
  sessionQueryVersion += 1;
  profileQueryVersion += 1;
  // 旧请求的 finally 按版本退出，当前动作自己接管随后的强制状态查询。
  loading.value = false;
  stopLoginWatch();
}

/**
 * 打开登录页之后加密轮询，登录一完成就把店铺名显示出来。
 *
 * 这里同时承担「后台确认」：后端已确认、只是本地回读没读到的动作会在这里自动重试，
 * 读到就自己收尾。用户登录完不需要回来点任何按钮。
 */
function startLoginWatch(durationMs = DEFAULT_LOGIN_WATCH_MS) {
  stopLoginWatch();
  const version = loginWatchVersion;
  const deadline = Date.now() + durationMs;
  loginWatchTimer = window.setInterval(async () => {
    if (version !== loginWatchVersion) return;
    if (Date.now() > deadline) {
      stopLoginWatch();
      return;
    }
    await refresh(true, true);
    if (version !== loginWatchVersion) return;
    if (session.value?.status === "logged_in") {
      const confirmingPending = Boolean(pendingAccountAction.value);
      const name = session.value.shop_name || session.value.shop_id;
      stopLoginWatch();
      await loadProfiles();
      if (confirmingPending) await retryPendingAction();
      // 只在「本次刚登录」时道贺；用户本来就在线时别每隔一会儿弹一次。
      if (confirmingPending && name) {
        ElMessage.success(`已登录：${name}，${loginPurpose.value}`);
      }
      return;
    }
    if (pendingAccountAction.value) await retryPendingAction();
  }, LOGIN_WATCH_INTERVAL_MS);
}

async function loadProfiles() {
  if (!componentActive) return null;
  const version = ++profileQueryVersion;
  try {
    const response = await api.getShopProfiles();
    if (version !== profileQueryVersion) return null;
    if (!response.success || !response.data) {
      throw new Error(response.message || response.msg || "后端未返回账户列表");
    }
    if (!Array.isArray(response.data.profiles) || !isValidProfileName(response.data.active_profile) || response.data.profiles.some((profile) =>
      !profile || !isValidProfileName(profile.profile_name) ||
      (profile.platform !== "douyin" && profile.platform !== "taobao" && profile.platform !== "xiaohongshu") || typeof profile.is_active !== "boolean"
    )) {
      throw new Error("账户列表响应缺少有效账户列表或选中编号");
    }
    const entries = response.data.profiles;
    const activeEntries = entries.filter((profile) => profile.is_active);
    if (entries.length > 0 && (new Set(entries.map((profile) => profile.profile_name)).size !== entries.length || activeEntries.length !== 1 || activeEntries[0].profile_name !== response.data.active_profile)) {
      throw new Error("账户列表存在重复编号或选中标记不一致，未确认账户状态");
    }
    profiles.value = response.data?.profiles ?? [];
    profileError.value = "";
    return response.data;
  } catch (error) {
    if (version !== profileQueryVersion) return null;
    profiles.value = [];
    profileError.value = `账户列表读取失败：${actionError(error)}`;
    return null;
  }
}

function onMenuVisibleChange(visible: boolean) {
  if (visible) void loadProfiles();
}

async function readBackAction(candidate: PendingAccountAction, version: number) {
  const current = await refresh(true, true);
  if (!isCurrentAccountAction(version)) return null;
  const listing = await loadProfiles();
  if (!isCurrentAccountAction(version)) return null;
  if (!current || !listing) {
    return { confirmed: false, message: sessionError.value || profileError.value || "账户状态与列表未能完整读取" };
  }
  if (!candidate.confirmed || !candidate.profileName) {
    return { confirmed: false, message: "已读到当前账户与列表，但原请求结果仍未知；当前同平台账户不能证明本次新增或切换已完成。" };
  }
  if (current.active_profile !== candidate.profileName || current.platform !== candidate.platform) {
    return { confirmed: false, message: "当前选中账户与目标不一致。请从账户菜单重新选择目标账户；系统不会自动改选。" };
  }
  const item = listing.profiles.find((profile) => profile.profile_name === candidate.profileName && profile.platform === candidate.platform);
  if (listing.active_profile !== candidate.profileName || !item || item.is_active !== true) {
    return { confirmed: false, message: "账户列表尚未确认目标账户已选中。" };
  }
  // 两个平台现在走同一条链路：只要该账户已被选中、且它出现在账户列表里，就算确认。
  // 早先这里要求淘宝的状态必须是 "manual"（本地未验证模式）——那是「淘宝只做本地
  // 资料准备」时代的约束；现在淘宝也走真实登录，那条断言会让淘宝账户操作**永远
  // 无法确认**。
  return { confirmed: true, message: "" };
}

function finishConfirmedAction(candidate: PendingAccountAction) {
  const name = session.value?.active_profile_label || candidate.label || candidate.profileName;
  ElMessage.success(
    `${platformName(candidate.platform)}账户「${name}」${candidate.kind === "add" ? "已添加并选中" : "已选中"}，请在打开的页面完成登录`
  );
  if (candidate.browserError) {
    ElMessage.warning(`账户选择已确认，但登录浏览器未能打开：${candidate.browserError}。可从账户菜单重新选择该账户重试。`);
  } else if (!candidate.browserOpened) {
    ElMessage.warning("账户选择已确认，但未收到登录浏览器已打开的确认。可从账户菜单重新选择该账户重试。");
  }
  // 两个平台都要盯登录：刚打开登录页这几分钟用户希望登录完马上看到店铺名。
  startLoginWatch();
}

/**
 * 把「后端已确认、本地还没读到」的动作交给后台跟进，不再弹阻塞窗口。
 *
 * 关键取舍：后端已经回成功，就不该再让用户手点一次「刷新并确认」——
 * 那是把用户当成两个系统之间的同步器。这里只记录、只重试，读到事实自己收尾。
 * 唯一的例外是「连后端确认都没拿到」（unverified），它必须让人看见，
 * 因为不能据此重发请求（可能已经生效）。
 */
function trackPendingAction(candidate: PendingAccountAction, message: string) {
  if (!pendingAccountAction.value) pendingAccountAction.value = candidate;
  if (candidate.phase === "awaiting_login") {
    // 拖住用户的窗口必须关掉：正常路径不该有阻断性的确认框。
    addDialogVisible.value = false;
    pendingFeedback.value = "";
  } else {
    // 结果未知是必须让用户看见的事实，但保留成可读的非阻断状态。
    addDialogVisible.value = true;
    pendingFeedback.value = message;
  }
  startLoginWatch();
}

/** POST 与 GET 回读分别确认，读到事实才算完成。 */
async function runShopAction(
  action: () => Promise<ApiResponse<ShopSwitchResult>>,
  failMessage: string,
  expectedPlatform: TargetPublishPlatform,
  kind: "add" | "switch",
  label: string,
  requestedProfile?: string
) {
  if (!componentActive || accountActionsDisabled.value) return false;
  if (kind === "add" && pendingAccountAction.value) {
    showAddAccount();
    return false;
  }
  const previousPending = pendingAccountAction.value;
  const version = ++accountActionVersion;
  switching.value = true;
  retirePendingSessionQuery();
  const candidate: PendingAccountAction = {
    kind, platform: expectedPlatform, label, profileName: null,
    phase: "unverified", stage: null, confirmed: false, browserError: null, browserOpened: false,
  };
  try {
    const response = await action();
    if (!isCurrentAccountAction(version)) return false;

    // 后端已确认（成功 + 账户标识合法）时，先把界面切到目标账户：
    // 「登录 = 就绪」靠的是这里的即时反馈，不是等回读。
    const data = response.success ? response.data : undefined;
    if (data && data.platform === expectedPlatform && isValidProfileName(data.active_profile) && (!requestedProfile || data.active_profile === requestedProfile)) {
      candidate.profileName = data.active_profile;
      candidate.confirmed = true;
      candidate.phase = "awaiting_login";
      candidate.stage = "login";
      candidate.browserError = data.browser_error || null;
      candidate.browserOpened = data.browser_opened === true;
      session.value = {
        platform: data.platform,
        active_profile: data.active_profile,
        active_profile_label: label || data.active_profile,
        profile_dir: data.profile_dir,
        status: "no_browser",
        shop_id: null,
        shop_name: null,
        debug_address: data.debug_address || null,
        error: null,
        detail: null,
      };
      sessionError.value = "";
      emit("changed", session.value);
      if (!previousPending) pendingAccountAction.value = candidate;

      const readBack = await readBackAction(candidate, version);
      if (!readBack || !isCurrentAccountAction(version)) return false;
      if (readBack.confirmed) {
        finishConfirmedAction(candidate);
        if (!previousPending) {
          pendingAccountAction.value = null;
          pendingFeedback.value = "";
          addDialogVisible.value = false;
        }
        return true;
      }
      // 后端说成功了，但连「当前选中哪家店」都还没读到：这时不能再叠账户操作。
      candidate.stage = "verify";
      trackPendingAction(candidate, `请求已返回成功，但当前账户确认未完成：${readBack.message}`);
      return false;
    }

    // 结果不完整：读不出后端到底做了什么，只能如实保留，禁止重复提交。
    trackPendingAction(
      candidate,
      response.success
        ? "返回的账户平台或编号无效，登记或选择结果尚未确认。请勿重复提交。"
        : `请求没有返回成功，但结果未知，不能据此重发：${response.message || response.msg || failMessage}。`
    );
    return false;
  } catch (error) {
    if (!isCurrentAccountAction(version)) return false;
    const reason = actionError(error);
    const status = axios.isAxiosError(error) ? error.response?.status : undefined;
    if (status && status >= 400 && status < 500 && status !== 408) {
      // 被明确拒绝 = 后端没有改变任何东西，可以安全地再点一次。
      ElMessage.error(`${failMessage}，请求已被拒绝：${reason}`);
      if (!previousPending) {
        pendingAccountAction.value = null;
        pendingFeedback.value = "";
      }
    } else {
      trackPendingAction(candidate, `请求结果未知：${reason}。可能已登记或改选账户；刷新只读取状态，不会重复提交。`);
    }
    return false;
  } finally {
    if (isCurrentAccountAction(version)) switching.value = false;
  }
}

function switchTo(profileName: string) {
  const profile = profiles.value.find((item) => item.profile_name === profileName);
  if (!profile) return;
  return runShopAction(
    () => api.switchShop(profileName, true),
    "切换账户失败",
    profile.platform,
    "switch",
    profile.label,
    profileName
  );
}

function showAddAccount() {
  if (accountActionsDisabled.value) return;
  const pending = pendingAccountAction.value;
  if (pending) {
    if (pending.phase === "awaiting_login" && pending.stage === "login") {
      // 账户本身已经确认，只是还没登录。允许继续添加下一个账户——
      // 但当前这个仍留在跟进列表里，用户回到它时不会再被拦一次。
      accountDraft.value = { platform: session.value?.platform || "douyin", label: "" };
      pendingFeedback.value = "";
      addDialogVisible.value = true;
      return;
    }
    if (pending.phase === "unverified") {
      // 结果未知不能重发，只把事实摆出来。
      addDialogVisible.value = true;
      return;
    }
    // 连「当前选中哪家店」都没读到：先去读，不给任何重复提交入口。
    void refreshPendingAction();
    return;
  }
  accountDraft.value = { platform: session.value?.platform || "douyin", label: "" };
  pendingFeedback.value = "";
  addDialogVisible.value = true;
}

async function addShop() {
  if (pendingAccountAction.value) return refreshPendingAction();
  const platform = accountDraft.value.platform;
  const label = accountDraft.value.label.trim();
  const succeeded = await runShopAction(
    () => api.addShop(platform, label),
    "添加账户失败",
    platform,
    "add",
    label
  );
  if (succeeded) addDialogVisible.value = false;
}

async function refreshPendingAction() {
  if (!componentActive || accountActionsDisabled.value || !pendingAccountAction.value) return false;
  const pending = pendingAccountAction.value;
  const version = ++accountActionVersion;
  switching.value = true;
  retirePendingSessionQuery();
  try {
    const readBack = await readBackAction(pending, version);
    if (!readBack || !isCurrentAccountAction(version) || pendingAccountAction.value !== pending) return false;
    if (!readBack.confirmed) {
      // 读不到就是「还没登录」或「后端结果仍未知」，都保留原状等下一次，
      // 不再顺手把界面清空——清空只会让用户以为账户丢了。
      if (pending.phase === "awaiting_login") pendingFeedback.value = "";
      else pendingFeedback.value = readBack.message;
      return false;
    }
    finishConfirmedAction(pending);
    pendingAccountAction.value = null;
    pendingFeedback.value = "";
    addDialogVisible.value = false;
    return true;
  } catch (error) {
    if (isCurrentAccountAction(version)) {
      pendingFeedback.value = `回读确认失败：${actionError(error)}。待确认结果已保留，请重新读取。`;
    }
    return false;
  } finally {
    if (isCurrentAccountAction(version)) switching.value = false;
  }
}

/**
 * 后台重试：登录轮询期间静默跟进，读到事实就自己收尾。
 * 不弹任何消息——它每 3 秒可能跑一次，弹出来就是打扰。
 */
async function retryPendingAction() {
  if (!componentActive || !pendingAccountAction.value || switching.value) return;
  const pending = pendingAccountAction.value;
  const version = ++accountActionVersion;
  switching.value = true;
  try {
    const readBack = await readBackAction(pending, version);
    if (!readBack || !isCurrentAccountAction(version) || pendingAccountAction.value !== pending) return;
    if (!readBack.confirmed) return;
    pendingAccountAction.value = null;
    pendingFeedback.value = "";
    addDialogVisible.value = false;
  } finally {
    if (isCurrentAccountAction(version)) switching.value = false;
  }
}

function dismissPendingNotice() {
  if (actionBusy.value) return;
  addDialogVisible.value = false;
}

/**
 * 为什么这个账户不能移除。
 *
 * 早先的做法是直接把移除按钮 `v-if` 掉——用户只看到按钮消失了，不知道原因，
 * 也不知道该做什么。后端有明确的拒绝理由，这里把它如实说出来。
 *
 * 现在**当前账户也可以删**（后端会把 active 交接给另一个仍然存在的账户），
 * 所以只剩「历史默认账户不能当空占位移除」这一种情况。
 */
function removeBlockedReason(profile: ShopProfile) {
  if (profile.removable) return "";
  return "该账户有店铺身份、备注或观测记录，不能作为默认空账户移除";
}

async function forgetShop(profile: ShopProfile) {
  if (accountActionsDisabled.value) return;
  if (!profile.removable) {
    ElMessage.warning(removeBlockedReason(profile));
    return;
  }
  const isActive = profile.is_active === true;
  try {
    await ElMessageBox.confirm(
      `彻底删除${platformName(profile.platform)}账户「${profile.label}」？\n\n` +
        "会同时删除它的本地浏览器登录资料，该账户的登录态将丢失，" +
        "下次重新添加需要重新登录。" +
        (isActive ? "\n\n它是当前账户，删除后会自动切换到另一个账户。" : ""),
      "删除账户",
      {
        type: "warning",
        confirmButtonText: "彻底删除",
        cancelButtonText: "取消",
      }
    );
  } catch {
    return;
  }
  if (accountActionsDisabled.value) return;
  switching.value = true;
  retirePendingSessionQuery();
  try {
    const response = await api.forgetShop(profile.profile_name, true);
    if (!response.success) {
      ElMessage.error(response.msg || "删除失败");
      return;
    }
    profiles.value = response.data?.profiles ?? [];
    if (response.data?.purged) {
      ElMessage.success("已彻底删除该账户及其本地登录资料");
    } else {
      // 后端如实回报了「记录已摘掉但目录没删干净」，这里不能报成成功删除。
      ElMessage.warning(response.msg || "已从列表移除，但登录资料未能完全删除");
    }
    await refresh(true, true);
  } catch (error) {
    ElMessage.error(`删除账户失败：${actionError(error)}`);
  } finally {
    switching.value = false;
  }
}

function handleCommand(command: string) {
  if (accountActionsDisabled.value) return;
  if (command === "add") return showAddAccount();
  if (command === "refresh") {
    // 有待跟进的动作时，「刷新账户状态」必须走确认那条路：
    // 它要顺带核对账户列表，只读一次会话不足以收尾。
    if (pendingAccountAction.value) return void refreshPendingAction();
    return void refresh(false, true);
  }
  if (command.startsWith("switch:")) return void switchTo(command.slice(7));
}

onMounted(async () => {
  await refresh(true);
  if (!componentActive) return;
  refreshTimer = window.setInterval(() => {
    if (document.visibilityState !== "hidden") {
      void refresh(true);
    }
  }, REFRESH_INTERVAL_MS);
});

onUnmounted(() => {
  componentActive = false;
  accountActionVersion += 1;
  sessionQueryVersion += 1;
  profileQueryVersion += 1;
  emit("busy-change", false);
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  stopLoginWatch();
});

defineExpose({ refresh, session });
</script>

<template>
  <div class="shop-bar">
    <el-dropdown
      trigger="click"
      :disabled="accountActionsDisabled"
      placement="bottom-start"
      popper-class="shop-menu"
      @command="handleCommand"
      @visible-change="onMenuVisibleChange"
    >
      <button class="shop-chip" type="button" :disabled="accountActionsDisabled" :title="hintText || statusText">
        <span class="chip-dot" :class="`dot-${statusKind}`" />
        <span v-if="session" class="chip-platform">{{ platformName(session.platform) }}</span>
        <span class="chip-name">{{ statusText }}</span>
        <el-icon class="chip-caret"><ArrowDown /></el-icon>
      </button>

      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item v-if="profileError" disabled>{{ profileError }}</el-dropdown-item>
          <el-dropdown-item
            v-for="profile in profiles"
            :key="profile.profile_name"
            :command="`switch:${profile.profile_name}`"
            :disabled="accountActionsDisabled"
          >
            <span class="item-icon">
              <el-icon v-if="profile.is_active"><Check /></el-icon>
            </span>
            <span class="item-platform">{{ platformName(profile.platform) }}</span>
            <span class="item-name">{{ profile.label }}</span>
            <span v-if="!profile.shop_id" class="item-state">未验证登录</span>
            <button
              type="button"
              :disabled="accountActionsDisabled || !profile.removable"
              class="item-remove"
              :title="profile.removable ? '从列表移除' : removeBlockedReason(profile)"
              :aria-label="
                profile.removable
                  ? `从列表移除${platformName(profile.platform)}账户${profile.label}`
                  : `${platformName(profile.platform)}账户${profile.label}不可移除：${removeBlockedReason(profile)}`
              "
              @click.stop="profile.removable ? forgetShop(profile) : undefined"
              @keydown.stop
            >
              <el-icon><Close /></el-icon>
            </button>
          </el-dropdown-item>

          <el-dropdown-item divided command="add" :disabled="accountActionsDisabled">
            <span class="item-icon"><el-icon><Plus /></el-icon></span>
            <span class="item-name">{{ pendingAccountAction?.confirmed ? "继续添加账户" : pendingAccountAction ? "重试确认账户" : "添加账户" }}</span>
          </el-dropdown-item>
          <el-dropdown-item command="refresh" :disabled="accountActionsDisabled || loading">
            <span class="item-icon"><el-icon><Refresh /></el-icon></span>
            <span class="item-name">刷新账户状态</span>
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>

    <el-dialog
      v-model="addDialogVisible"
      :title="pendingAccountAction?.kind === 'switch' ? '账户待确认' : '添加发布账户'"
      width="440px"
      :close-on-click-modal="false"
      :close-on-press-escape="!actionBusy"
      :show-close="!actionBusy"
    >
      <el-form v-if="!pendingAccountAction" label-position="top" :disabled="accountActionsDisabled">
        <el-form-item label="账户平台" required>
          <el-radio-group v-model="accountDraft.platform">
            <el-radio-button value="douyin">抖音 / 抖店</el-radio-button>
            <el-radio-button value="taobao">淘宝</el-radio-button>
            <el-radio-button value="xiaohongshu">小红书千帆</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="账户名称（选填）">
          <el-input v-model="accountDraft.label" placeholder="填写便于识别的本地账户名称" maxlength="60" />
        </el-form-item>
      </el-form>
      <template v-else>
        <p class="account-hint">
          目标平台：{{ platformName(pendingAccountAction.platform) }}；
          本地名称或账户编号：{{ pendingAccountAction.label || pendingAccountAction.profileName || '未确认' }}。
        </p>
        <el-alert
          title="本次请求的结果还没读到"
          :description="pendingFeedback"
          type="warning"
          :closable="false"
          show-icon
        />
        <p class="account-hint">“重试确认”只读取当前账户与列表，不会再次提交添加或切换。</p>
      </template>
      <p v-if="!pendingAccountAction" class="account-hint">发布路线由账户平台决定。添加后自动选中该账户并打开登录页，登录成功即完成确认，不需要再点一次。</p>
      <p class="account-hint">
        添加后会自动打开该账户专用的登录浏览器。两个平台行为一致：登录完成后自动读取账户身份；
        读不到就如实显示「未登录」，不会拿本地的账户备注冒充店铺身份。
      </p>
      <el-alert
        v-if="(pendingAccountAction?.platform || accountDraft.platform) === 'taobao'"
        title="淘宝账户：登录后自动读取账户身份"
        :description="taobaoNote"
        type="info"
        :closable="false"
        show-icon
      />
      <p
        v-else-if="(pendingAccountAction?.platform || accountDraft.platform) === 'xiaohongshu'"
        class="account-hint"
      >
        添加后打开小红书千帆登录页；登录完成后读取店铺名（来源为页面元素，属候选级证据），
        读不到就如实显示「未读到」，不会拿本地账户备注冒充店铺身份。
      </p>
      <p v-else class="account-hint">添加后打开抖店登录页，店铺身份以实际登录检测结果为准。</p>
      <template #footer>
        <template v-if="pendingAccountAction">
          <el-button :disabled="actionBusy" @click="dismissPendingNotice">知道了</el-button>
          <el-button type="primary" :loading="switching" :disabled="accountActionsDisabled" @click="refreshPendingAction">重试确认</el-button>
        </template>
        <template v-else>
          <el-button :disabled="actionBusy" @click="addDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="switching" :disabled="accountActionsDisabled" @click="addShop">添加账户</el-button>
        </template>
      </template>
    </el-dialog>
  </div>
</template>

<style lang="scss" scoped>
.shop-bar {
  display: flex;
  align-items: center;
  padding: 10px 16px 0;
}

.shop-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  padding: 5px 9px;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  // 原生 button 不继承页面字体，不写这行芯片里的字会和周围不一致
  font-family: inherit;
  line-height: 1.4;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;

  &:hover,
  &:focus-visible {
    border-color: var(--border-color);
    background: rgba(92, 124, 250, 0.07);
  }

  &:disabled {
    cursor: not-allowed;
    opacity: 0.65;
  }
}

.chip-platform,
.item-platform {
  flex: none;
  padding: 1px 5px;
  border-radius: var(--radius-sm);
  background: var(--el-fill-color);
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.item-platform {
  margin-right: 8px;
}

.item-state {
  flex: none;
  margin-left: 10px;
  color: var(--el-color-warning-dark-2);
  font-size: 12px;
}

.account-hint {
  margin: 8px 0 16px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.chip-dot {
  flex: none;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-placeholder);
}

.dot-ok {
  background: #2f9e44;
}

.dot-warn {
  background: #d9822b;
}

.dot-error {
  background: #c0392b;
}

.chip-name {
  min-width: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-caret {
  flex: none;
  font-size: 12px;
  color: var(--text-secondary);
}

.item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  margin-right: 6px;
  color: var(--text-secondary);
}

.item-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

// 移除只在悬停该行时露出来，平时不占视觉重量。
.item-remove {
  display: inline-flex;
  align-items: center;
  margin-left: 12px;
  color: var(--text-placeholder);
  border: 0;
  padding: 2px;
  background: transparent;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, color 0.15s ease;

  &:hover {
    color: #c0392b;
  }

  &:focus-visible {
    opacity: 1;
    outline: 2px solid var(--primary-color);
    outline-offset: 2px;
  }
}
</style>

<style lang="scss">
.shop-menu {
  min-width: 200px;

  .el-dropdown-menu__item {
    display: flex;
    align-items: center;

    &:hover .item-remove {
      opacity: 1;
    }
  }
}
</style>
