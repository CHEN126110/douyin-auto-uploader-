import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { ElLoading, ElMessage, ElMessageBox } from "element-plus";
import { api, initializeApi } from "@/services/api";
import type { Product, ProductDetail } from "@/types";

export const useProductStore = defineStore("product", () => {
  const products = ref<Product[]>([]);
  const currentProduct = ref<ProductDetail | null>(null);
  const currentProductId = ref<number | null>(null);
  const loading = ref(false);
  const detailLoading = ref(false);
  const backendStatus = ref<"checking" | "online" | "offline">("checking");
  const importingFiles = ref(false);

  const detailCache = ref<Map<number, ProductDetail>>(new Map());

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

  async function saveProduct(data: Partial<ProductDetail>) {
    try {
      const response = await api.saveInfo({
        _id: currentProductId.value!,
        ...data,
      });
      if (response.success) {
        if (currentProductId.value) {
          detailCache.value.delete(currentProductId.value);
        }
        return true;
      }
      return false;
    } catch (error) {
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
    try {
      const response = await api.deleteProduct(id);
      if (response.success) {
        setProducts(products.value.filter((product) => product.id !== id));
        detailCache.value.delete(id);
        return true;
      }
      return false;
    } catch (error) {
      console.error("Failed to delete product:", error);
      return false;
    }
  }

  async function deleteAll() {
    try {
      const response = await api.deleteAll();
      if (response.success) {
        setProducts([]);
        currentProduct.value = null;
        currentProductId.value = null;
        detailCache.value.clear();
        return true;
      }
      return false;
    } catch (error) {
      console.error("Failed to clear products:", error);
      return false;
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
        if (false && duplicateProducts.length > 0) {
          const preview = duplicateProducts
            .slice(0, 5)
            .map((product: any) => {
              const groups = product.duplicate_groups || [];
              const detailText = groups
                .map((group: any) => `- ${group.display_name} x${group.count}`)
                .join("\n");
              return `《${product.product_name}》\n${detailText}`;
            })
            .join("\n\n");
          const extraCount = duplicateProducts.length - 5;
          const extraText =
            extraCount > 0 ? `\n\n还有 ${extraCount} 个商品未展开显示。` : "";

          await ElMessageBox.alert(
            `导入已完成，但以下商品存在重复 SKU 名称，上传前请先修改：\n\n${preview}${extraText}`,
            "重复 SKU 预警",
            { type: "warning" }
          );
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

  async function startUpload(recordId?: number) {
    try {
      return await api.startUpload(recordId);
    } catch (error) {
      console.error("Failed to start upload:", error);
      return { success: false, msg: "上传失败" };
    }
  }

  async function getUploadStatus(taskId: string) {
    try {
      return await api.getUploadStatus(taskId);
    } catch (error) {
      console.error("Failed to get upload status:", error);
      return {
        success: false,
        data: {
          task_id: taskId,
          record_id: 0,
          record_name: "",
          status: "failed" as const,
          progress: 0,
          message: "获取状态失败",
          error: String(error),
        },
        msg: "获取状态失败",
      };
    }
  }

  function clearCache() {
    detailCache.value.clear();
  }

  function invalidateCache(id: number) {
    detailCache.value.delete(id);
  }

  return {
    products,
    currentProduct,
    currentProductId,
    loading,
    detailLoading,
    backendStatus,
    importingFiles,
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
    clearCache,
    invalidateCache,
  };
});
