import { ref, watch } from "vue";
import type { Ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import { confirmAction } from "@/utils/dialog";

/**
 * 左侧「本地商品目录」的交互：点选商品、右键菜单（图片管理 / 打开文件夹 / 删除）、
 * 清空全部，以及商品列表载入后自动选中第一个商品。发布进行中（uploadBusy）这些操作都让路。
 */
export function useProductList({ uploadBusy }: { uploadBusy: Readonly<Ref<boolean>> }) {
  const productStore = useProductStore();
  let autoSelectingFirstProduct = false;

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

  return {
    contextMenuVisible,
    contextMenuPosition,
    mediaManagerVisible,
    mediaManagerProductId,
    handleProductMenuKey,
    handleContextMenu,
    handleContextMenuAction,
    handleProductClick,
    handleDeleteAll,
  };
}
