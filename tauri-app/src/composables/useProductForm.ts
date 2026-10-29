import { computed, ref, watch } from "vue";
import type { Ref } from "vue";
import { ElMessage } from "element-plus";
import { useProductStore } from "@/stores/productStore";
import { countTaobaoTitleUnits } from "@/utils/taobaoTextLength";
import type { SKU } from "@/types";
import type { useSkuList } from "@/composables/useSkuList";

type SkuListState = ReturnType<typeof useSkuList>;

/**
 * 右侧商品表单：类目 / 标题 / 备注 / 库存 / 单价，随当前商品载入，
 * 以及「保存」「简单填充价格」。发布流程要读它（见 usePublishFlow），所以表单数据由这里统一持有。
 */
export function useProductForm({
  uploadBusy,
  selectedSkuPaths,
  duplicateSkuGroups,
  showDuplicateSkuAlert,
}: {
  uploadBusy: Readonly<Ref<boolean>>;
  selectedSkuPaths: SkuListState["selectedSkuPaths"];
  duplicateSkuGroups: SkuListState["duplicateSkuGroups"];
  showDuplicateSkuAlert: SkuListState["showDuplicateSkuAlert"];
}) {
  const productStore = useProductStore();

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
    },
    { immediate: true }
  );

  function productSaveData(form: typeof formData.value, skus: SKU[]) {
    const data: Record<string, string | number | null> = {
      title: form.title.trim(), remark: form.remark,
      repo: form.repo, clazz: form.clazz, attr_size: skus.length,
    };
    skus.forEach((sku, index) => {
      data[`attr_path_${index + 1}`] = sku.path;
      data[`attr_name_${index + 1}`] = sku.name.trim();
      data[`attr_price_${index + 1}`] = sku.price;
      data[`attr_remark_${index + 1}`] = sku.remark ?? "";
      data[`attr_pair_count_${index + 1}`] = sku.spec_values?.双数 ?? "";
    });
    return data;
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

  return { formData, titleLength, productSaveData, handleSave, handleSimpleFill };
}

export type ProductFormData = ReturnType<typeof useProductForm>["formData"]["value"];
