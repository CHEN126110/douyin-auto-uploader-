import { computed, onMounted, ref } from "vue";
import type { Ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api, apiErrorMessage, apiErrorRejectedExplicitly, apiErrorStatus } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import { confirmAction } from "@/utils/dialog";
import { CATEGORY_OPTIONS } from "@/types";
import type { PublishSubmitMode, TaobaoProductRequest, TargetPublishPlatform } from "@/types";
import type { ProductFormData, useProductForm } from "@/composables/useProductForm";
import type { useShopAccount } from "@/composables/useShopAccount";
import type { useSkuList } from "@/composables/useSkuList";
import type { UploadTaskMonitor } from "@/composables/useUploadTaskMonitor";

/**
 * 发起发布：抖音（浏览器自动发布 / 协议上传）、淘宝（填写并回读）、小红书千帆（只填不提交），
 * 以及「批量发布全部待上传商品」。
 *
 * 抖音和淘宝的安全顺序一致：先校验当前商品与账户 → 提交方式是「直接发布」时必须人工确认店铺 →
 * 把当前编辑内容存盘并拿到后端确认的版本号 → 才真正启动任务 → 把任务交给 useUploadTaskMonitor 跟进。
 * 小红书千帆只填表不提交，不走存盘与发布确认。任何一步对不上都停下来如实提示，不重试、不绕过。
 */
export function usePublishFlow({
  monitor,
  shop,
  formData,
  productSaveData,
  collectDuplicateSkuGroups,
  showDuplicateSkuAlert,
}: {
  monitor: UploadTaskMonitor;
  shop: ReturnType<typeof useShopAccount>;
  formData: Ref<ProductFormData>;
  productSaveData: ReturnType<typeof useProductForm>["productSaveData"];
  collectDuplicateSkuGroups: ReturnType<typeof useSkuList>["collectDuplicateSkuGroups"];
  showDuplicateSkuAlert: ReturnType<typeof useSkuList>["showDuplicateSkuAlert"];
}) {
  const productStore = useProductStore();
  const {
    isUploadMonitoring,
    isUploadStarting,
    taobaoUnknownStart,
    ensureUploadLoading,
    closeUploadLoading,
    startUploadMonitoring,
    syncExternalUploadTask,
  } = monitor;
  const { shopStatusBarRef, shopSession, shopAccountBusy } = shop;

  // 提交方式：'publish' 直接提交上架，'stop' 全部填好后停下不提交。
  // 读不到设置时保守取 stop——发布不可撤销，宁可让用户手动确认一次。
  const publishSubmitMode = ref<PublishSubmitMode>("stop");

  async function loadPublishSubmitMode() {
    try {
      const response = await api.getSettings();
      const resolved = response?.data?.settings?.automation_config?.publish_submit_mode_effective;
      publishSubmitMode.value = resolved === "publish" ? "publish" : "stop";
    } catch (error) {
      publishSubmitMode.value = "stop";
    }
  }

  const publishPlatformLabel = computed(() =>
    productStore.targetPublishPlatform === "douyin" ? "抖音" :
      productStore.targetPublishPlatform === "taobao" ? "淘宝" : (productStore.targetPublishPlatform === "xiaohongshu" ? "小红书千帆" : "")
  );
  const publishActionText = computed(() => `开始${publishPlatformLabel.value}发布`);
  const publishButtonDisabled = computed(() =>
    !productStore.targetPublishPlatform || isUploadMonitoring.value ||
      isUploadStarting.value || Boolean(taobaoUnknownStart.value) || shopAccountBusy.value ||
      productStore.detailLoading
  );

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
      const reason = apiErrorMessage(error);
      ElMessage.error(`抖音发布启动失败：${reason}`);
    } finally {
      isUploadStarting.value = false;
    }
  }

  /** 一键批量发布全部待上传商品（抖音/淘宝，status=0）。 */
  async function handleBatchUploadAll() {
    if (publishButtonDisabled.value) return;
    const platform = productStore.targetPublishPlatform;
    if (!platform) {
      ElMessage.warning("请先在左上角连接店铺账户，再使用批量发布");
      return;
    }
    if (platform !== "douyin" && platform !== "taobao" && platform !== "xiaohongshu") {
      ElMessage.warning("批量发布支持抖音、淘宝和小红书，请先切换到对应账户");
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

    const pendingCount = productStore.products.filter((p: any) => p.status === 0).length;
    if (pendingCount === 0) {
      ElMessage.warning("没有待上传的商品（status=0）");
      return;
    }

    const confirmed = await confirmAction(
      `将依次发布 <b>${pendingCount}</b> 个待上传商品到${publishPlatformLabel.value}。是否继续？`,
      "批量发布确认",
      {
        type: "warning",
        dangerouslyUseHTMLString: true,
        confirmButtonText: "开始批量发布",
        cancelButtonText: "取消",
      }
    );
    if (!confirmed) return;

    isUploadStarting.value = true;
    try {
      await loadPublishSubmitMode();
      const realPublish = publishSubmitMode.value === "publish";
      if (realPublish && !(await confirmRealPublish())) {
        return;
      }

      ensureUploadLoading(realPublish ? "正在批量提交发布…" : "正在启动批量上传…");
      let response: any;
      if (platform === "douyin") {
        response = await productStore.startUploadAll(
          realPublish ? { confirmFinalPublish: true } : { stopBeforeSubmit: true }
        );
      } else if (platform === "xiaohongshu") {
        response = await api.startXhsFillBatch({
          allowUpload: true,
          allowAdvance: true,
          serviceValues: {
            物流模板: "【系统创建】物流模板默认—联系人",
            运费模板: "系统默认-全国包邮模版",
            物流类型: "普通内贸",
          },
        });
      } else {
        response = await api.startTaobaoPublishAll({
          realPublish,
          fillOnly: !realPublish,
          accountProfile: productStore.currentShopSession?.active_profile,
        });
      }
      if (!response.success) {
        closeUploadLoading();
        ElMessage.error(response.message || response.msg || "批量上传启动失败");
        return;
      }
      const taskId = (response as any)?.data?.task_id as string | undefined;
      if (!taskId) {
        closeUploadLoading();
        ElMessage.error("批量上传启动失败：未获取到任务编号");
        return;
      }
      startUploadMonitoring(taskId, "local", null, platform as any);
    } catch (error) {
      closeUploadLoading();
      const reason = apiErrorMessage(error);
      ElMessage.error(`批量发布启动失败：${reason}`);
    } finally {
      isUploadStarting.value = false;
    }
  }

  /** 小红书千帆单个商品填表（只填不提交）。 */
  async function handleXhsFill() {
    const recordId = productStore.currentProductId;
    const record = productStore.currentProduct;
    if (!recordId || record?.id !== recordId) {
      ElMessage.warning("请先选择并加载一个商品，再开始小红书填表");
      return;
    }
    const title = formData.value.title.trim() || (record?.title || "").trim();
    if (!title) {
      ElMessage.warning("请填写商品标题");
      return;
    }
    const skus = productStore.currentSkus;
    const images = skus.map((sku: any) => sku.path).filter(Boolean);
    const categoryLabel = CATEGORY_OPTIONS.find((entry) => entry.value === formData.value.clazz)?.label || "";
    isUploadStarting.value = true;
    try {
      ensureUploadLoading("正在小红书填表…");
      const response = await api.xhsFillOnly({
        title,
        images,
        allow_upload: true,
        allow_advance: true,
        category: categoryLabel,
        service_values: {
          物流模板: "【系统创建】物流模板默认—联系人",
          运费模板: "系统默认-全国包邮模版",
          物流类型: "普通内贸",
        },
      });
      closeUploadLoading();
      const report = response?.data as any;
      if (report?.ok) {
        await ElMessageBox.alert(
          "小红书填表完成。该平台只填不提交，请到千帆后台核对后手动发布",
          "填表完成",
          { type: "success" }
        );
      } else {
        const blocked = Array.isArray(report?.blocked) ? report.blocked.join("；") : "未知原因";
        // 失败时把**具体原因**一并带出来（计划 1.1）：否则只看到「图片上传未成功」这类笼统话 ✗，
        // 无法判断是路径不存在、超 5M、格式不对，还是点完没出现文件框。
        const details: string[] = [];
        for (const step of Array.isArray(report?.steps) ? report.steps : []) {
          if (step && step.ok === false && step.reason) details.push(`${step.name}：${step.reason}`);
        }
        for (const item of Array.isArray(report?.resolved_images) ? report.resolved_images : []) {
          if (item && item.ok === false) {
            const name = String(item.path || "").split(/[\\/]/).pop() || "(未命名)";
            details.push(`图片 ${name}：${item.problem || "不可用"}`);
          }
        }
        const gaps = report?.gaps;
        if (gaps && Array.isArray(gaps.unfilled) && gaps.unfilled.length) {
          details.push(`仍缺必填：${gaps.unfilled.join("、")}`);
        }
        const text = details.length
          ? `未完成填表：${blocked}；具体原因 —— ${details.join("；")}`
          : `未完成填表：${blocked}`;
        await ElMessageBox.alert(text, "填表结果", { type: "warning" });
      }
    } catch (error) {
      closeUploadLoading();
      const reason = apiErrorMessage(error);
      ElMessage.error(`小红书填表失败：${reason}`);
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
    if (productStore.targetPublishPlatform === "xiaohongshu") {
      await handleXhsFill();
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
    if (skus.some((sku) => !String(sku.spec_values?.双数 ?? "").trim())) {
      ElMessage.warning("请填写每条 SKU 的双数（按实际商品填数值，例如 1 或 2）");
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
        spec_values: { ...(sku.spec_values || {}), "颜色分类": sku.name.trim() },
        price: sku.price as number, // 上方已逐条校验为正数；空价格不能进入请求。
        stock,
        ...(sku.path ? { image_path: sku.path } : {}),
      })),
    };
    isUploadStarting.value = true;
    try {
      // 提交模式可能在设置里被改过，每次上传前重新读，别用启动时的旧值发布。
      await loadPublishSubmitMode();
      const realPublish = publishSubmitMode.value === "publish";
      if (realPublish && !(await confirmRealPublish())) {
        return;
      }
      ensureUploadLoading("正在保存当前商品资料…");
      const savedRevision = await savePublishSnapshot(snapshot);
      if (!savedRevision) {
        closeUploadLoading();
        return;
      }
      ensureUploadLoading(realPublish ? "正在提交发布…" : "正在启动上传…");
      requestedAt = Date.now();
      const response = await productStore.startTaobaoFill(recordId, product, accountProfile, savedRevision, {
        ...(realPublish ? { realPublish: true } : {}),
      });
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
      if (realPublish) {
        if (data.dry_run !== false || data.stop_before_submit !== false) {
          ElMessage.warning("后端返回的任务模式与直接发布要求不一致，已接上进度，请核对任务状态");
        }
      } else if (data.dry_run !== false || data.stop_before_submit !== true) {
        ElMessage.warning("后端返回的任务模式与提交前填写要求不一致，已接上进度，请核对任务状态");
      }
    } catch (error) {
      closeUploadLoading();
      const reason = apiErrorMessage(error);
      const status = apiErrorStatus(error);
      const explicitlyRejected = apiErrorRejectedExplicitly(error);
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

  onMounted(() => {
    void loadPublishSubmitMode();
  });

  return {
    publishPlatformLabel,
    publishActionText,
    publishButtonDisabled,
    handlePublishByAccount,
    handleBatchUploadAll,
  };
}
