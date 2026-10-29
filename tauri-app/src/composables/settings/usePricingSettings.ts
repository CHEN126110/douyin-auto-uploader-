/**
 * 设置页「价格设置」的表单模型：目标毛利率 + 成本项目。
 *
 * 由 SettingsPanel 创建并持有（加载、保存、未保存提示都要用到它），
 * PricingTab 通过 props 拿到同一个对象就地编辑。不是全局状态：每个 SettingsPanel 实例各有一份。
 */
import { reactive, ref } from "vue";
import type { CostItem, Settings } from "@/types";

export function usePricingSettings() {
  // 基础配置
  const pricingConfig = ref({
    target_gross_margin: 30,     // 目标毛利率（%）
  });

  // 成本项目列表（可增删改）
  const costItems = ref<CostItem[]>([
    { id: "1", name: "单位成本", cost_type: "per_unit", value: 8.0, description: "每双袜子的基础成本" },
    { id: "2", name: "运费", cost_type: "fixed", value: 5.0, description: "物流运输费用" },
    { id: "3", name: "包装费", cost_type: "fixed", value: 1.0, description: "包装材料费用" },
    { id: "4", name: "平台佣金", cost_type: "percentage", value: 6, description: "平台抽成比例" },
  ]);

  /** 用后端返回的设置覆盖表单；后端没给的字段保持表单里现有的值。 */
  function applySettings(settings: Settings) {
    // 加载价格配置
    if (settings.pricing_config) {
      const pc = settings.pricing_config;
      // 后端返回的是百分比形式（如30），直接使用，不需要乘以100
      const rawValue = pc.target_gross_margin ?? 30;
      // 如果值小于1，说明是小数形式（0.30），需要转换为百分比
      pricingConfig.value = {
        target_gross_margin: rawValue < 1 ? rawValue * 100 : rawValue,
      };
      console.log("[Settings] 加载毛利率配置:", rawValue, "->", pricingConfig.value.target_gross_margin);
    }

    // 加载成本项目
    if (settings.cost_items && Array.isArray(settings.cost_items)) {
      costItems.value = settings.cost_items;
      console.log("[Settings] 加载成本项目:", costItems.value.length, "个");
    }
  }

  /** 保存时提交给后端的价格部分。后端期望百分比形式（如30），直接发送输入框的值。 */
  function buildPayload(): Pick<Settings, "pricing_config" | "cost_items"> {
    return {
      pricing_config: {
        target_gross_margin: pricingConfig.value.target_gross_margin,
      },
      cost_items: costItems.value,
    };
  }

  return reactive({ pricingConfig, costItems, applySettings, buildPayload });
}

export type PricingSettingsModel = ReturnType<typeof usePricingSettings>;
