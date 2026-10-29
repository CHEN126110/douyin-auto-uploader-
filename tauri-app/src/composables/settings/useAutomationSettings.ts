/**
 * 设置页「自动化设置」的表单模型：发布方式 / 提交方式 / 采集偏好 / 运费模板 / 材质面料 / 水洗标。
 *
 * 由 SettingsPanel 创建并持有（加载、保存、未保存提示、保存前校验都要用到它），
 * AutomationTab 及其子区块通过 props 拿到同一个对象就地编辑。
 *
 * 运费模板的读取也在这里：读取成功时会用店铺的名单改写 `shippingTemplates`，而这个列表同时是
 * 要保存的设置，所以读取必须排在加载设置之后（先加载设置，再读店铺），由 SettingsPanel 来调度。
 */
import { computed, reactive, ref, watch } from "vue";
import { ElMessage } from "element-plus";
import { api, apiErrorMessage } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import type {
  AutomationConfig,
  CaptureMode,
  CapturePreferences,
  FreightTemplate,
  MaterialComposition,
  PublishSubmitMode,
  Settings,
} from "@/types";

export function normalizeMaterialCompositions(
  source?: Array<Partial<MaterialComposition>> | null
): MaterialComposition[] {
  return Array.isArray(source)
    ? source
        .map((item) => ({
          material: String(item?.material ?? "").trim(),
          percentage: Number(item?.percentage ?? 0),
        }))
        .filter((item) => item.material && Number.isFinite(item.percentage) && item.percentage > 0)
    : [];
}

export function useAutomationSettings() {
  const productStore = useProductStore();

  // 运费模板名单：下拉框的选项，也是保存进设置的 shipping_templates。真源是店铺
  // （见 loadFreightTemplates），这里只是缓存，读不到店铺时下拉框还有东西可选。
  //   - 只有两处会改写它：加载设置（换成已保存的名单）、读店铺成功（换成店铺的名单）。
  //   - 读取没成功（没有会话 / 接口失败 / 没读到）时必须保持原样，不能清空：
  //     它会随设置一起保存，清空再保存就把已缓存的名单覆盖成了默认值。
  //   - 界面上没有任何地方能让用户增删它，程序刷新它不算「用户改动」，所以不参与
  //     SettingsPanel 的未保存提示；用户能改的是下面的 selectedShippingTemplate。
  const shippingTemplates = ref<string[]>([]);
  // 当前选中的运费模板
  const selectedShippingTemplate = ref("");

  // 运费模板来自店铺，不在本地维护。每家店的模板都不一样，让用户手工填一份名单，
  // 名字打错或换了店就会在发布时选错模板甚至失败，而且不会有任何报错。
  const freightLoading = ref(false);
  const freightShopName = ref("");
  const freightError = ref("");
  const freightTemplates = ref<FreightTemplate[]>([]);
  let freightQueryVersion = 0;
  const materialOptions = ref<string[]>([]);
  const materialCompositions = ref<MaterialComposition[]>([]);
  const washLabelTagImagePath = ref("");
  const publishMode = ref("dom");
  // 提交方式：publish 直接提交上架，stop 全部填好后停下不提交
  const publishSubmitMode = ref<PublishSubmitMode>("publish");
  // 采集偏好：分平台独立配置。1688 和 淘宝/天猫 是两个独立平台，采集协议互不交叉。
  //   - dom（默认）：读浏览器渲染数据（1688 走 window.context；淘宝/天猫 走 mtop SDK）
  //   - protocol（预览版）：CDP 网络拦截抓接口响应，目前数据提取仍回退到 DOM，
  //     主要价值是会把协议层网络快照保存到工件目录，方便后续抓包分析。
  const capturePreferences = ref<CapturePreferences>({
    alibaba_1688_mode: "dom",
    taobao_tmall_mode: "dom",
  });

  const materialPercentageTotal = computed(() =>
    Number(materialCompositions.value
      .reduce((sum, item) => sum + Number(item.percentage || 0), 0)
      .toFixed(6))
  );
  const materialSettingsInvalid = computed(() => {
    // 材质允许自定义输入：平台会不断新增面料，写死白名单会把新材质挡在外面。
    // 这里只保证「非空」与「含量合计 100%」，是否为平台标准项交由 isCustomMaterial 提示。
    const hasEmptyMaterial = materialCompositions.value.some((item) => !item.material);
    return materialPercentageTotal.value !== 100 || hasEmptyMaterial;
  });

  /**
   * 保存的模板名在这家店里不存在时必须说出来。
   *
   * 发布流程不会因此报错：DOM 路径找不到就退到兜底值「包邮」，协议路径按「包含」
   * 匹配到名字相近的一个。两条都会发出去，只是运费规则和用户以为的不一样，
   * 而且只在日志里留一行。这种静默偏差要在设置里就拦住。
   */
  const selectedTemplateMissing = computed(() => {
    if (!selectedShippingTemplate.value || freightTemplates.value.length === 0) return false;
    return !freightTemplates.value.some((t) => t.name === selectedShippingTemplate.value);
  });

  async function loadFreightTemplates(notify = false) {
    const version = ++freightQueryVersion;
    const account = productStore.currentShopSession;
    // 只重置「这一次读取」的展示状态。shippingTemplates 是要保存的缓存，
    // 只有读取成功（见下方）才允许改写，读取失败时保留原来的名单。
    freightTemplates.value = [];
    freightShopName.value = "";
    freightError.value = "";
    // 两个平台都读，只是读法不同：
    //   抖店 —— 协议接口（已实证）；
    //   淘宝 —— **DOM**，从发布表单的运费模板下拉里读（2026-10-03 接通）。
    // 原先这里对淘宝直接 return，界面上永远是「需切换到抖音账户」——
    // 而后端其实也一直没能读，两边一起把这件事挡住了。
    if (account?.platform !== "douyin" && account?.platform !== "taobao" && account?.platform !== "xiaohongshu") {
      freightLoading.value = false;
      freightError.value = "当前账户未确认，请返回主页面刷新账户状态";
      if (notify) ElMessage.warning(freightError.value);
      return;
    }
    freightLoading.value = true;
    try {
      const response = await api.getShopFreightTemplates();
      if (version !== freightQueryVersion || productStore.currentShopSession?.active_profile !== account.active_profile) return;
      const data = response.data;
      if (!response.success || !data) {
        throw new Error(response.message || response.msg || "后端未返回运费模板");
      }
      freightShopName.value = data?.shop_name || "";
      freightError.value = data?.error || "";
      const templates = data?.templates ?? [];
      freightTemplates.value = templates;
      if (templates.length > 0) {
        shippingTemplates.value = templates.map((t) => t.name);
        if (notify) ElMessage.success(`已读取 ${templates.length} 个运费模板`);
      } else {
        // ⚠️ **「没读到」与「没有模板」是两件事。**
        //
        // status !== "ok" 说明这次读取本身没成功（页面不对、下拉没展开、结构变了），
        // 绝不能显示成「该店铺没有模板」——那会让人以为不用配运费模板就能发布。
        const reason = data?.error || "没有读到运费模板";
        const hint = data?.status === "need_publish_page"
          ? "淘宝的运费模板下拉只在「发布表单」里：请先在淘宝发布工作台打开一个商品的发布页，再回来刷新。"
          : data?.status === "read_failed"
            ? "下拉展开了但一个选项都没读到；这不等于该店铺没有模板。"
            : "";
        freightError.value = hint ? reason + "。" + hint : reason;
        if (notify) ElMessage.warning(freightError.value);
      }
    } catch (error) {
      if (version !== freightQueryVersion) return;
      const reason = apiErrorMessage(error);
      freightError.value = `读取运费模板失败：${reason}`;
      if (notify) ElMessage.error(freightError.value);
    } finally {
      if (version === freightQueryVersion) freightLoading.value = false;
    }
  }

  watch(
    [() => productStore.currentShopSession?.active_profile, () => productStore.currentShopSession?.platform],
    () => { void loadFreightTemplates(); }
  );

  /** 用后端返回的设置覆盖表单；没有 automation_config 时保持表单现状。 */
  function applySettings(settings: Settings) {
    // 加载自动化配置
    if (settings.automation_config) {
      const ac = settings.automation_config as AutomationConfig;
      // 加载模板列表
      if (ac.shipping_templates && Array.isArray(ac.shipping_templates)) {
        shippingTemplates.value = ac.shipping_templates
          .map((item) => String(item).trim())
          .filter(Boolean);
      }
      // 加载当前选中的模板
      if (ac.shipping_template) {
        selectedShippingTemplate.value = ac.shipping_template;
        // 确保选中的模板在列表中
        if (!shippingTemplates.value.includes(ac.shipping_template)) {
          shippingTemplates.value.push(ac.shipping_template);
        }
      }
      if (!selectedShippingTemplate.value) {
        selectedShippingTemplate.value = shippingTemplates.value[0] || "";
      }
      if (ac.material_options && Array.isArray(ac.material_options)) {
        materialOptions.value = ac.material_options;
      }
      materialCompositions.value = normalizeMaterialCompositions(ac.material_compositions);
      washLabelTagImagePath.value = String(ac.wash_label_tag_image_path || "").trim();
      publishMode.value = String(ac.publish_mode || "dom").trim();
      // 历史配置里可能存着 auto，以后端规范化后的值为准
      publishSubmitMode.value =
        (ac.publish_submit_mode_effective ?? ac.publish_submit_mode) === "stop"
          ? "stop"
          : "publish";

      // 加载采集偏好（分平台独立）
      // 兼容旧的单一字段 capture_mode：如果新字段缺失就用旧字段作为两个平台的初始值
      const legacyCaptureMode = String(ac.capture_mode || "dom").trim();
      const prefs = ac.capture_preferences;
      const normalizeMode = (v: unknown): CaptureMode => (v === "protocol" ? "protocol" : "dom");
      capturePreferences.value = {
        alibaba_1688_mode: normalizeMode(prefs?.alibaba_1688_mode ?? legacyCaptureMode),
        taobao_tmall_mode: normalizeMode(prefs?.taobao_tmall_mode ?? legacyCaptureMode),
      };
      console.log("[Settings] 加载自动化配置:", {
        templates: shippingTemplates.value,
        selected: selectedShippingTemplate.value,
        materialOptions: materialOptions.value,
        materials: materialCompositions.value,
        washLabelTagImagePath: washLabelTagImagePath.value,
        capturePreferences: capturePreferences.value,
      });
    }
  }

  /** 保存时提交给后端的 automation_config。 */
  function buildPayload(): AutomationConfig {
    return {
      shipping_template: selectedShippingTemplate.value,
      shipping_templates: shippingTemplates.value,
      material_options: materialOptions.value,
      material_compositions: normalizeMaterialCompositions(materialCompositions.value),
      wash_label_tag_image_path: washLabelTagImagePath.value.trim() || null,
      publish_mode: publishMode.value,
      publish_submit_mode: publishSubmitMode.value,
      // 分平台采集偏好：1688 和 淘宝/天猫 独立保存
      capture_preferences: {
        alibaba_1688_mode: capturePreferences.value.alibaba_1688_mode,
        taobao_tmall_mode: capturePreferences.value.taobao_tmall_mode,
      },
    };
  }

  return reactive({
    shippingTemplates,
    selectedShippingTemplate,
    freightLoading,
    freightShopName,
    freightError,
    freightTemplates,
    materialOptions,
    materialCompositions,
    washLabelTagImagePath,
    publishMode,
    publishSubmitMode,
    capturePreferences,
    materialPercentageTotal,
    materialSettingsInvalid,
    selectedTemplateMissing,
    loadFreightTemplates,
    applySettings,
    buildPayload,
  });
}

export type AutomationSettingsModel = ReturnType<typeof useAutomationSettings>;
