import { computed, ref, watch } from "vue";
import type { Ref } from "vue";
import { ElMessage } from "element-plus";
import { useProductStore } from "@/stores/productStore";
import { confirmAction } from "@/utils/dialog";
import type { SKU } from "@/types";

/**
 * SKU 列表的勾选与重复名检查：
 * - 勾选：填充价格只作用于勾选的 SKU，切换商品时清空勾选；
 * - 重复名：同一个商品里规格名称重复时，保存 / 发布前要拦住并提示。
 * 发布进行中（uploadBusy）所有改动操作都让路。
 */
export function useSkuList({ uploadBusy }: { uploadBusy: Readonly<Ref<boolean>> }) {
  const productStore = useProductStore();

  // 选中的SKU
  const selectedSkuPaths = ref<Set<string>>(new Set());

  // 换了商品，上一个商品的勾选就没有意义了
  watch(
    () => productStore.currentProduct,
    () => {
      selectedSkuPaths.value.clear();
    }
  );

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

  function handleCancelSelect() {
    if (uploadBusy.value) return;
    selectedSkuPaths.value.clear();
    ElMessage.success("已取消选择");
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

  return {
    selectedSkuPaths,
    duplicateSkuGroups,
    duplicateSkuPaths,
    collectDuplicateSkuGroups,
    showDuplicateSkuAlert,
    handleCancelSelect,
    handleSkuSelect,
    handleSkuDelete,
  };
}
