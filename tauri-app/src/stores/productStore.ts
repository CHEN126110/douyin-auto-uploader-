import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ElLoading, ElMessage } from "element-plus";
import { api, initializeApi } from "@/services/api";
import type {
  Product,
  ProductDetail,
  ProductMediaListing,
  ProductSaveOptions,
  UploadStartOptions,
  TargetPublishPlatform,
  ShopSessionState,
  TaobaoPublishPayload,
  TaobaoProductRequest,
} from "@/types";

export const useProductStore = defineStore("product", () => {
  const products = ref<Product[]>([]);
  const currentProduct = ref<ProductDetail | null>(null);
  const currentProductId = ref<number | null>(null);
  const loading = ref(false);
  const detailLoading = ref(false);
  const backendStatus = ref<"checking" | "online" | "offline">("checking");
  const importingFiles = ref(false);
  const currentShopSession = ref<ShopSessionState | null>(null);
  const mediaListing = ref<ProductMediaListing | null>(null);
  const mediaLoading = ref(false);
  const whiteBgSaving = ref(false);
  const mediaError = ref("");
  let mediaRequestVersion = 0;

  function clearMediaListing() {
    mediaRequestVersion += 1;
    mediaListing.value = null;
    mediaLoading.value = false;
    mediaError.value = "";
  }

  async function loadMediaDirectory(recordId: number, path = "", offset = 0) {
    const version = ++mediaRequestVersion;
    const profile = currentShopSession.value?.active_profile || "";
    mediaListing.value = null;
    mediaLoading.value = true;
    mediaError.value = "";
    try {
      const response = await api.getProductMedia(recordId, path, profile, offset);
      if (version !== mediaRequestVersion) return;
      if (!response.success || !response.data) {
        throw new Error(response.msg || response.message || "图片目录读取失败");
      }
      if (response.data.record_id !== recordId || response.data.path !== path ||
          response.data.account_profile !== profile ||
          (currentShopSession.value?.active_profile || "") !== profile) {
        throw new Error("商品或账户已经变化，请刷新图片目录");
      }
      mediaListing.value = response.data;
    } catch (error) {
      if (version !== mediaRequestVersion) return;
      const failure = error as { response?: { data?: { msg?: string } }; message?: string };
      mediaError.value = failure.response?.data?.msg || failure.message || "图片目录读取失败";
    } finally {
      if (version === mediaRequestVersion) mediaLoading.value = false;
    }
  }
  async function setWhiteBgSelection(recordId: number, path: string) {
    if (whiteBgSaving.value) return false;
    whiteBgSaving.value = true;
    lastActionError.value = null;
    try {
      const response = await api.setProductWhiteBg(recordId, path);
      if (!response.success || !response.data) {
        throw new Error(response.msg || response.message || "白底图选择保存失败");
      }
      const result = response.data;
      if (result.record_id !== recordId || result.selection.path !== path) {
        throw new Error("白底图选择回执与当前操作不一致，请刷新查看");
      }
      if (mediaListing.value?.record_id === recordId) {
        mediaListing.value.white_bg_selection = result.selection;
      }
      detailCache.value.delete(recordId);
      if (currentProduct.value?.id === recordId) {
        currentProduct.value.white_bg_path = result.selection.path;
        currentProduct.value.update_time = result.update_time;
      }
      return true;
    } catch (error) {
      const failure = error as { response?: { data?: { msg?: string } }; message?: string };
      lastActionError.value = failure?.response?.data?.msg || failure?.message || String(error);
      return false;
    } finally {
      whiteBgSaving.value = false;
    }
  }

  const targetPublishPlatform = computed<TargetPublishPlatform | null>(() =>
    currentShopSession.value?.platform ?? null
  );

  const detailCache = ref<Map<number, ProductDetail>>(new Map());
  // 后端的真实失败原因（response.message）。
  // 原来各动作只返回 true/false，把 message 丢掉，界面只能弹一句笼统的「清空失败」——
  // 实测 2026-10-01：「清空失败」背后其实是
  //   「移动到回收站失败，系统错误码: 120」/「attempt to write a readonly database」
  // 两种完全不同的故障，却看不到任何线索，排障只能靠翻后端日志。
  const lastActionError = ref<string | null>(null);

  let lastImportTime = 0;
  let lastImportPaths: string[] = [];
  let lastProductsSignature = "";
  let silentRefreshInFlight = false;

  const hasProducts = computed(() => products.value.length > 0);
  const currentSkus = computed(() => currentProduct.value?.content || []);
  const isBackendOnline = computed(() => backendStatus.value === "online");

  function hasSkuImages(detail: ProductDetail | null | undefined) {
    return Boolean(detail?.content?.some((sku) => Boolean(sku.url)));
  }

  function mergeSkuImageUrls(
    nextDetail: ProductDetail,
    previousDetail?: ProductDetail | null
  ) {
    if (!previousDetail?.content?.length || !nextDetail.content?.length) {
      return nextDetail;
    }

    const existingUrlMap = new Map(
      previousDetail.content
        .filter((sku) => sku.path && sku.url)
        .map((sku) => [sku.path, sku.url])
    );

    if (existingUrlMap.size === 0) {
      return nextDetail;
    }

    const isInvalidSkuUrl = (value: string | undefined) => {
      if (!value) return true;
      return (
        value.startsWith("data:image/svg+xml;base64,") &&
        (value.includes("Tm8gSW1hZ2U") || value.includes("TG9hZCBFcnJvcg"))
      );
    };

    return {
      ...nextDetail,
      content: nextDetail.content.map((sku) => ({
        ...sku,
        url: isInvalidSkuUrl(sku.url) ? existingUrlMap.get(sku.path) : sku.url,
      })),
    };
  }

  function buildProductsSignature(items: Product[]) {
    return items
      .map((product) => `${product.id}|${product.name}|${product.update_time}`)
      .sort()
      .join("||");
  }

  function setProducts(nextProducts: Product[]) {
    products.value = nextProducts;
    lastProductsSignature = buildProductsSignature(nextProducts);

    if (
      currentProductId.value &&
      !nextProducts.some((product) => product.id === currentProductId.value)
    ) {
      currentProduct.value = null;
      currentProductId.value = null;
    }
  }

  async function refreshCurrentProductSilently() {
    const id = currentProductId.value;
    if (!id || detailLoading.value) {
      return false;
    }

    try {
      const previousDetail =
        currentProduct.value?.id === id
          ? currentProduct.value
          : detailCache.value.get(id) || null;
      const response = await api.loadDetail(id, false);
      if (!response.success || !response.data) {
        return false;
      }

      const mergedDetail = mergeSkuImageUrls(response.data, previousDetail);
      currentProduct.value = mergedDetail;
      detailCache.value.set(id, mergedDetail);
      return true;
    } catch {
      return false;
    }
  }

  async function initialize() {
    backendStatus.value = "checking";
    const serviceReady = await initializeApi();
    let loaded = await fetchProducts({ silent: !serviceReady });
    for (let retry = 0; !loaded && retry < 6; retry += 1) {
      await new Promise((resolve) => setTimeout(resolve, 700));
      loaded = await fetchProducts({ silent: true });
    }
    backendStatus.value = loaded ? "online" : "offline";
  }

  async function fetchProducts(options: { silent?: boolean } = {}) {
    const { silent = false } = options;
    if (!silent) {
      loading.value = true;
    }

    try {
      const response = await api.getProducts();
      if (response.success) {
        setProducts(response.products || []);
        console.log(`Loaded product list: ${products.value.length}`);
        return true;
      }
      return false;
    } catch (error) {
      if (!silent) {
        console.error("Failed to fetch product list:", error);
      }
      return false;
    } finally {
      if (!silent) {
        loading.value = false;
      }
    }
  }

  async function refreshProductsSilently() {
    if (
      silentRefreshInFlight ||
      backendStatus.value !== "online" ||
      importingFiles.value
    ) {
      return false;
    }

    silentRefreshInFlight = true;
    try {
      const response = await api.getProducts();
      if (!response.success) {
        return false;
      }

      const nextProducts = response.products || [];
      const nextSignature = buildProductsSignature(nextProducts);
      if (nextSignature === lastProductsSignature) {
        return false;
      }

      const currentSummary = currentProductId.value
        ? nextProducts.find((product) => product.id === currentProductId.value)
        : null;
      const shouldRefreshCurrentDetail =
        Boolean(currentSummary) &&
        currentProduct.value?.update_time !== currentSummary?.update_time;

      setProducts(nextProducts);
      if (shouldRefreshCurrentDetail) {
        await refreshCurrentProductSilently();
      }
      console.log(`Background synced product list: ${products.value.length}`);
      return true;
    } catch {
      return false;
    } finally {
      silentRefreshInFlight = false;
    }
  }

  async function loadProductDetail(id: number) {
    const cachedDetail = detailCache.value.get(id);
    if (cachedDetail) {
      currentProduct.value = cachedDetail;
      currentProductId.value = id;
      if (hasSkuImages(cachedDetail) || cachedDetail.content.length === 0) {
        return;
      }
    }

    detailLoading.value = true;
    try {
      const response = await api.loadDetail(id);
      if (response.success && response.data) {
        const mergedDetail = mergeSkuImageUrls(response.data, cachedDetail);
        currentProduct.value = mergedDetail;
        currentProductId.value = id;
        detailCache.value.set(id, mergedDetail);
      }
    } catch (error) {
      console.error("Failed to load product detail:", error);
    } finally {
      detailLoading.value = false;
    }
  }

  async function saveProduct(data: Partial<ProductDetail>, options: ProductSaveOptions = {}) {
    lastActionError.value = null;
    const recordId = options.recordId ?? currentProductId.value;
    if (!recordId) {
      lastActionError.value = "请先选择一个商品";
      return false;
    }
    if (options.publishPlatform) {
      const account = currentShopSession.value;
      if (account?.platform !== options.publishPlatform || !options.accountProfile ||
          account.active_profile !== options.accountProfile) {
        lastActionError.value = "店铺账户已改变，未保存本次上传资料";
        return false;
      }
    }
    // 响应丢失也可能已经写入；下一次载入必须取服务端的实际记录。
    detailCache.value.delete(recordId);
    try {
      const response = await api.saveInfo({
        ...data,
        _id: recordId,
        ...(options.publishPlatform ? {
          for_publish: true,
          platform: options.publishPlatform,
          account_profile: options.accountProfile,
        } : {}),
      });
      if (response.success) {
        if (response.data?.id !== recordId) {
          lastActionError.value = "保存结果没有确认当前商品，未继续上传";
          return false;
        }
        if (options.publishPlatform && !/^[a-f0-9]{64}$/.test(response.data.record_revision || "")) {
          lastActionError.value = "后端没有确认已保存的商品资料版本，未继续上传";
          return false;
        }
        return response.data;
      }
      lastActionError.value = response.message || response.msg || "后端未返回失败原因";
      return false;
    } catch (error) {
      lastActionError.value = error instanceof Error ? error.message : String(error);
      console.error("Failed to save product:", error);
      return false;
    }
  }

  async function deleteSku(skuPath: string) {
    if (!currentProductId.value) return false;

    try {
      const response = await api.deleteSku(skuPath, currentProductId.value);
      if (response.success) {
        if (currentProduct.value) {
          currentProduct.value.content = currentProduct.value.content.filter(
            (sku) => sku.path !== skuPath
          );
        }
        detailCache.value.delete(currentProductId.value);
        return true;
      }
      return false;
    } catch (error) {
      console.error("Failed to delete SKU:", error);
      return false;
    }
  }

  async function deleteProduct(id: number) {
    lastActionError.value = null;
    try {
      const response = await api.deleteProduct(id);
      if (response.success) {
        setProducts(products.value.filter((product) => product.id !== id));
        detailCache.value.delete(id);
        return true;
      }
      lastActionError.value = response.message || response.msg || "后端未返回失败原因";
      return false;
    } catch (error) {
      lastActionError.value = error instanceof Error ? error.message : String(error);
      console.error("Failed to delete product:", error);
      return false;
    }
  }

  async function deleteAll() {
    lastActionError.value = null;
    try {
      const response = await api.deleteAll();
      if (response.success) {
        setProducts([]);
        currentProduct.value = null;
        currentProductId.value = null;
        detailCache.value.clear();
        return true;
      }
      lastActionError.value = response.message || response.msg || "后端未返回失败原因";
      return false;
    } catch (error) {
      lastActionError.value = error instanceof Error ? error.message : String(error);
      console.error("Failed to clear products:", error);
      return false;
    } finally {
      // 清空可能只完成前几项，失败后必须显示后端实际仍存在的商品。
      if (lastActionError.value) {
        detailCache.value.clear();
        if (!(await fetchProducts({ silent: true }))) {
          lastActionError.value += "；列表刷新失败，请稍后刷新查看实际结果";
        }
      }
    }
  }

  async function importFiles(filePaths: string[]) {
    if (importingFiles.value) {
      ElMessage.warning("正在导入中，请稍候...");
      return;
    }

    if (!filePaths || filePaths.length === 0) {
      ElMessage.warning("没有选择文件");
      return;
    }

    const now = Date.now();
    const sortedPaths = [...filePaths].sort();
    const isSamePaths =
      sortedPaths.length === lastImportPaths.length &&
      sortedPaths.every((path, index) => path === lastImportPaths[index]);

    if (isSamePaths && now - lastImportTime < 2000) {
      console.log("Skipped duplicate import request");
      return;
    }

    lastImportTime = now;
    lastImportPaths = sortedPaths;

    const uniquePaths = [...new Set(filePaths)];

    importingFiles.value = true;
    const loadingInstance = ElLoading.service({
      lock: true,
      text: `正在导入 ${uniquePaths.length} 个文件夹...`,
      background: "rgba(0, 0, 0, 0.7)",
    });

    try {
      const response = await api.importFolders(uniquePaths);

      if (response.success) {
        const importedCount = response.data?.imported_count || 0;
        ElMessage.success(
          importedCount > 0
            ? `成功导入 ${importedCount} 个文件夹`
            : response.msg || "导入成功"
        );

        await fetchProducts();

        if (products.value.length > 0 && !currentProductId.value) {
          await loadProductDetail(products.value[0].id);
        }

        const duplicateProducts = response.data?.duplicate_sku_products || [];
        if (duplicateProducts.length > 0) {
          ElMessage.warning({
            message:
              duplicateProducts.length === 1
                ? "有 1 个商品里出现了重复规格。已帮你标出来了，改一下就可以继续保存或上传。"
                : `有 ${duplicateProducts.length} 个商品里出现了重复规格。已帮你标出来了，改一下就可以继续保存或上传。`,
            showClose: true,
            duration: 0,
          });
        }

        if (response.data?.errors?.length) {
          console.warn("Some folders failed to import:", response.data.errors);
        }
      } else {
        ElMessage.error(response.msg || "导入失败");
      }
    } catch (error) {
      console.error("Failed to import folders:", error);
      ElMessage.error("导入失败，请确保后端服务已启动");
    } finally {
      importingFiles.value = false;
      loadingInstance.close();
    }
  }

  async function importFromPicker() {
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        directory: true,
        multiple: true,
        title: "选择产品文件夹",
      });

      if (selected && Array.isArray(selected) && selected.length > 0) {
        await importFiles(selected);
      }
    } catch (error) {
      console.error("Failed to open file picker:", error);
      ElMessage.error("无法打开文件选择器");
    }
  }

  async function startUpload(recordId?: number, options?: UploadStartOptions) {
    const account = currentShopSession.value;
    if (account?.platform !== "douyin" || !account.active_profile) {
      throw new Error("当前抖音账户未确认，请刷新账户状态后重试");
    }
    return await api.startUpload(recordId, {
      ...options,
      accountProfile: options?.accountProfile ?? account.active_profile,
    });
  }

  // 拿不到状态 ≠ 上传失败：后端上传跑在后台线程里，轮询失败不影响它。
  // 这里让传输层异常如实上抛，由调用方决定重试还是终止监控。
  async function getUploadStatus(taskId: string) {
    return await api.getUploadStatus(taskId);
  }

  async function startTaobaoFill(recordId: number, product: TaobaoProductRequest, accountProfile: string, expectedRecordRevision?: string) {
    const account = currentShopSession.value;
    if (account?.platform !== "taobao" || account.active_profile !== accountProfile) {
      throw new Error("当前淘宝账户已经变化，未启动填写任务");
    }
    return await api.startTaobaoPublish(recordId, {
      accountProfile,
      product,
      dryRun: false,
      stopBeforeSubmit: true,
      fillOnly: true,
      expectedRecordRevision,
    });
  }

  // 淘宝资料只读本地商品，表单覆盖值由独立面板持有；请求失败如实上抛。
  async function checkTaobaoPreparation(payload: TaobaoPublishPayload) {
    return await api.prepareTaobaoProduct(payload);
  }

  async function exportTaobaoPacket(payload: TaobaoPublishPayload) {
    return await api.exportTaobaoPacket(payload);
  }

  function setShopSession(state: ShopSessionState | null) {
    currentShopSession.value = state;
  }

  function clearCache() {
    detailCache.value.clear();
  }

  function invalidateCache(id: number) {
    detailCache.value.delete(id);
  }

  return {
    mediaListing,
    mediaLoading,
    mediaError,
    whiteBgSaving,
    setWhiteBgSelection,
    loadMediaDirectory,
    clearMediaListing,
    products,
    currentProduct,
    currentProductId,
    loading,
    detailLoading,
    backendStatus,
    lastActionError,
    importingFiles,
    targetPublishPlatform,
    currentShopSession,
    hasProducts,
    currentSkus,
    isBackendOnline,
    initialize,
    fetchProducts,
    refreshProductsSilently,
    refreshCurrentProductSilently,
    loadProductDetail,
    saveProduct,
    deleteSku,
    deleteProduct,
    deleteAll,
    importFiles,
    importFromPicker,
    startUpload,
    getUploadStatus,
    startTaobaoFill,
    checkTaobaoPreparation,
    exportTaobaoPacket,
    setShopSession,
    clearCache,
    invalidateCache,
  };
});
