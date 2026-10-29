<script setup lang="ts">
import type { PricingResultsData } from "@/types";

// 弹窗显示与否由主页控制（v-model）；内容由 useSmartPricing 算好后传进来，这里只负责展示。
const visible = defineModel<boolean>({ required: true });
defineProps<{ result: PricingResultsData }>();

// 获取利润率颜色
function getProfitColor(margin: number): string {
  if (margin >= 30) return "#27ae60"; // 绿色 - 良好
  if (margin >= 20) return "#f39c12"; // 黄色 - 一般
  return "#e74c3c"; // 红色 - 偏低
}
</script>

<template>
  <el-dialog
    v-model="visible"
    title="📊 智能填充成本分析结果"
    width="1200px"
    top="5vh"
    class="pricing-results-dialog"
    :lock-scroll="false"
    :close-on-click-modal="false"
    destroy-on-close
    center
  >
    <!-- 配置与统计信息 -->
    <div class="config-info">
      <span class="config-tag">🎯 目标毛利率: {{ result.configUsed.target_gross_margin }}%</span>
      <span class="config-tag">💰 单价: ¥{{ result.unitPrice.toFixed(2) }}/双</span>
      <span class="config-tag">📦 固定: ¥{{ result.configUsed.fixed_costs.toFixed(2) }}</span>
      <span class="config-tag">💳 百分比: {{ result.configUsed.percentage_costs }}%</span>
      <span class="config-tag divider">|</span>
      <span class="config-tag success">✅ {{ result.statistics.total_skus }}个SKU</span>
      <span class="config-tag info">📊 均价¥{{ result.statistics.average_price.toFixed(2) }}</span>
      <span class="config-tag profit">📈 区间¥{{ result.statistics.min_price.toFixed(2) }}-{{ result.statistics.max_price.toFixed(2) }}</span>
    </div>

    <!-- 详细表格 - 支持水平滚动 -->
    <div class="table-scroll-wrapper">
      <el-table 
        :data="result.results" 
        stripe
        border
        max-height="350"
        class="pricing-table"
        size="small"
        table-layout="fixed"
      >
        <el-table-column prop="sku_name" label="SKU名称" min-width="150">
          <template #default="{ row }">
            <span class="sku-name-cell">{{ row.sku_name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="数量" align="center">
          <template #default="{ row }">
            <span class="quantity-cell">{{ row.quantity }}</span>
          </template>
        </el-table-column>
        <el-table-column label="单价" align="center">
          <template #default="{ row }">
            <span class="unit-price-cell">¥{{ (row.sock_cost / row.quantity).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="袜子成本" align="center">
          <template #default="{ row }">
            <span class="cost-cell">¥{{ row.sock_cost?.toFixed(2) || '0.00' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="固定成本" align="center">
          <template #default="{ row }">
            <span class="fixed-cost-cell">¥{{ row.fixed_costs?.toFixed(2) || '0.00' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="百分比成本" align="center">
          <template #default="{ row }">
            <span class="percentage-cost-cell">¥{{ row.percentage_cost?.toFixed(2) || '0.00' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="总成本" align="center">
          <template #default="{ row }">
            <span class="total-cost-cell">¥{{ row.total_cost?.toFixed(2) || '0.00' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="suggested_price" label="建议售价" align="center">
          <template #default="{ row }">
            <span class="suggested-price">¥{{ row.suggested_price?.toFixed(2) || '0.00' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="毛利率" align="center">
          <template #default="{ row }">
            <span 
              class="profit-margin"
              :style="{ color: getProfitColor(row.profit_margin || 0) }"
            >
              {{ row.profit_margin?.toFixed(1) || '0.0' }}%
            </span>
          </template>
        </el-table-column>
        <el-table-column label="利润" align="center">
          <template #default="{ row }">
            <span 
              class="profit-amount"
              :style="{ color: (row.profit || 0) >= 0 ? '#27ae60' : '#e74c3c' }"
            >
              ¥{{ row.profit?.toFixed(2) || '0.00' }}
            </span>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 说明 -->
    <div class="pricing-tips">
      <p><strong>💡 成本计算公式：</strong></p>
      <ul>
        <li><strong>总成本</strong> = 袜子成本 + 固定成本 + 百分比成本</li>
        <li><strong>建议售价</strong> = 总成本 ÷ (1 - 目标毛利率 - 百分比成本率)</li>
        <li><strong>毛利率颜色</strong>：<span style="color:#27ae60">绿色≥30%</span> | <span style="color:#f39c12">黄色≥20%</span> | <span style="color:#e74c3c">红色&lt;20%</span></li>
      </ul>
      <p class="tip-note">💡 可在「设置」中调整成本项目和目标毛利率</p>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button type="primary" @click="visible = false">
          确定
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<!-- 注意：这一块样式没有 scoped（拆分前就是全局样式），.config-info / .pricing-table 等类名全局生效。
     写在 .pricing-results-dialog 与 .pricing-table 里的 :deep(...) 在非 scoped 样式中浏览器不认，
     实际是无效规则（拆分前就是如此）；为保持界面一字不差，原样保留，没有改成生效。 -->
<style lang="scss">
// 智能填充结果弹窗
.pricing-results-dialog {
  :deep(.el-dialog) {
    max-height: 90vh;
    display: flex;
    flex-direction: column;
  }
  
  :deep(.el-dialog__header) {
    padding: 16px 20px;
    border-bottom: 1px solid #ebeef5;
    margin-right: 0;
  }
  
  :deep(.el-dialog__body) {
    padding: 16px 20px;
    flex: 1;
    overflow-y: auto;
  }
  
  :deep(.el-dialog__footer) {
    padding: 12px 20px;
    border-top: 1px solid #ebeef5;
  }
}

.config-info {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 12px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(92, 124, 250, 0.08) 0%, rgba(92, 124, 250, 0.03) 100%);
  border-radius: 8px;
  border: 1px solid rgba(92, 124, 250, 0.15);
  
  .config-tag {
    font-size: 13px;
    color: #5c7cfa;
    font-weight: 500;
    padding: 4px 10px;
    background: rgba(255, 255, 255, 0.6);
    border-radius: 4px;
    
    &.divider {
      background: transparent;
      color: rgba(92, 124, 250, 0.3);
      padding: 0 4px;
    }
    
    &.success {
      color: #27ae60;
      background: rgba(39, 174, 96, 0.1);
    }
    
    &.info {
      color: #3498db;
      background: rgba(52, 152, 219, 0.1);
    }
    
    &.profit {
      color: #9b59b6;
      background: rgba(155, 89, 182, 0.1);
    }
  }
}

.pricing-summary {
  display: none;  // 已合并到 config-info
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  
  .summary-item {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 8px 14px;
    border-radius: 6px;
    font-size: 13px;
    
    .label {
      color: #6c757d;
      font-size: 12px;
    }
    
    .value {
      font-weight: 600;
      font-size: 14px;
    }
    
    &.success {
      background: rgba(39, 174, 96, 0.1);
      .value { color: #27ae60; }
    }
    
    &.info {
      background: rgba(52, 152, 219, 0.1);
      .value { color: #3498db; }
    }
    
    &.profit {
      background: rgba(155, 89, 182, 0.1);
      .value { color: #9b59b6; }
    }
    
    &.warning {
      background: rgba(230, 126, 34, 0.1);
      .value { color: #e67e22; }
    }
  }
}

// 表格滚动容器
.table-scroll-wrapper {
  width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  
  // 美化滚动条
  &::-webkit-scrollbar {
    height: 8px;
  }
  
  &::-webkit-scrollbar-track {
    background: #f1f1f1;
    border-radius: 4px;
  }
  
  &::-webkit-scrollbar-thumb {
    background: #c1c1c1;
    border-radius: 4px;
    
    &:hover {
      background: #a8a8a8;
    }
  }
}

.pricing-table {
  font-size: 12px;
  width: 100%;
  min-width: 1080px;
  
  :deep(.el-table__header th) {
    background-color: #f8f9fa !important;
    font-weight: 600;
    color: #495057;
    padding: 8px 12px;
    white-space: nowrap; // 表头不换行
  }
  
  :deep(.el-table__row td) {
    padding: 6px 12px;
  }
  
  :deep(.el-table__cell) {
    white-space: nowrap; // 单元格内容不换行
  }
  
  .sku-name-cell {
    white-space: nowrap;
    font-weight: 500;
  }
  
  .quantity-cell {
    color: #6c757d;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .unit-price-cell {
    color: #2ecc71;
    font-weight: 600;
    font-size: 12px;
    white-space: nowrap;
  }
  
  .cost-cell {
    color: #3498db;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .fixed-cost-cell {
    color: #17a2b8;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .percentage-cost-cell {
    color: #6f42c1;
    font-weight: 600;
    white-space: nowrap;
  }
  
  .total-cost-cell {
    color: #495057;
    font-weight: 700;
    white-space: nowrap;
  }
  
  .suggested-price {
    color: #e67e22;
    font-weight: bold;
    font-size: 13px;
    white-space: nowrap;
  }
  
  .profit-margin {
    font-weight: bold;
    white-space: nowrap;
  }
  
  .profit-amount {
    font-weight: bold;
    white-space: nowrap;
  }
}

.pricing-tips {
  margin-top: 14px;
  padding: 12px 14px;
  background: rgba(39, 174, 96, 0.06);
  border-radius: 6px;
  border-left: 3px solid #27ae60;
  font-size: 12px;
  color: #2d5a2d;
  line-height: 1.5;
  
  p {
    margin: 0 0 6px;
  }
  
  ul {
    margin: 0;
    padding-left: 18px;
    
    li {
      margin-bottom: 3px;
    }
  }
  
  .tip-note {
    margin-top: 8px;
    color: #5c7cfa;
    font-style: italic;
  }
}
</style>
