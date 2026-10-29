import { nextTick, ref } from "vue";
import type { Ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "@/services/api";
import { useProductStore } from "@/stores/productStore";
import type { PricingResult, PricingResultsData } from "@/types";
import type { ProductFormData } from "@/composables/useProductForm";

/**
 * 「智能填充」：按设置里的成本项和目标毛利率，为每个 SKU 算出建议售价并填进去，
 * 再弹出成本分析结果。
 */
export function useSmartPricing({
  uploadBusy,
  formData,
}: {
  uploadBusy: Readonly<Ref<boolean>>;
  formData: Ref<ProductFormData>;
}) {
  const productStore = useProductStore();

  // 智能填充价格（基于成本项目计算）
  const smartFillLoading = ref(false);
  const pricingResultsVisible = ref(false);

  const pricingResultsData = ref<PricingResultsData>({
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

  return { smartFillLoading, pricingResultsVisible, pricingResultsData, handleSmartFill };
}
