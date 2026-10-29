<script setup lang="ts">
import { computed, ref, toRefs } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import type { CostItem } from "@/types";
import type { PricingSettingsModel } from "@/composables/settings/usePricingSettings";

// 价格设置表单由 SettingsPanel 持有（加载 / 保存 / 未保存提示都靠它），本 Tab 就地编辑；
// 下面只放本 Tab 自己的界面状态（正在编辑哪一行、添加表单等）。
const props = defineProps<{ model: PricingSettingsModel }>();
const { pricingConfig, costItems } = toRefs(props.model);

// 当前编辑的成本项索引（-1表示未编辑）
const editingCostIndex = ref(-1);

// 新增成本项
const newCostItem = ref<CostItem>({
  id: "",
  name: "",
  cost_type: "fixed",
  value: 0,
  description: "",
});

// 是否显示添加表单
const showAddForm = ref(false);

// 添加成本项
function addCostItem() {
  if (!newCostItem.value.name.trim()) {
    ElMessage.warning("请输入成本项名称");
    return;
  }

  costItems.value.push({
    ...newCostItem.value,
    id: Date.now().toString(),
  });

  // 重置表单
  newCostItem.value = {
    id: "",
    name: "",
    cost_type: "fixed",
    value: 0,
    description: "",
  };
  showAddForm.value = false;

  ElMessage.success("添加成功");
}

// 取消添加
function cancelAddCostItem() {
  newCostItem.value = {
    id: "",
    name: "",
    cost_type: "fixed",
    value: 0,
    description: "",
  };
  showAddForm.value = false;
}

// 删除成本项
async function removeCostItem(index: number) {
  try {
    await ElMessageBox.confirm("确定删除该成本项吗？", "提示", {
      type: "warning",
    });
    costItems.value.splice(index, 1);
    editingCostIndex.value = -1;
    ElMessage.success("删除成功");
  } catch {
    // 用户取消
  }
}

// 开始编辑成本项
function startEditCostItem(index: number) {
  editingCostIndex.value = index;
}

// 完成编辑
function finishEditCostItem() {
  editingCostIndex.value = -1;
}

// 获取单位
function getUnit(type: string): string {
  return type === "percentage" ? "%" : "元";
}

// 获取类型标签样式
function getTypeTagType(type: string): "success" | "warning" | "info" {
  switch (type) {
    case "fixed":
      return "info";
    case "per_unit":
      return "warning";
    case "percentage":
      return "success";
    default:
      return "info";
  }
}

// 获取类型显示名称
function getTypeName(type: string): string {
  switch (type) {
    case "fixed":
      return "固定";
    case "per_unit":
      return "按数量";
    case "percentage":
      return "百分比";
    default:
      return type;
  }
}

// 计算成本汇总
const costSummary = computed(() => {
  let fixed = 0;
  let perUnit = 0;
  let percentage = 0;

  for (const item of costItems.value) {
    switch (item.cost_type) {
      case "fixed":
        fixed += item.value;
        break;
      case "per_unit":
        perUnit += item.value;
        break;
      case "percentage":
        percentage += item.value;
        break;
    }
  }

  return { fixed, perUnit, percentage };
});
</script>

<template>
  <!-- 毛利率配置 -->
  <div class="settings-section">
    <h3 class="section-title">📈 毛利率配置</h3>
    <div class="config-row">
      <div class="config-item">
        <label>目标毛利率</label>
        <div class="config-input">
          <el-input
            v-model.number="pricingConfig.target_gross_margin"
            type="number"
            :min="0"
            :max="100"
          />
          <span class="unit">%</span>
        </div>
      </div>
    </div>
  </div>

  <!-- 成本项目管理 -->
  <div class="settings-section">
        <div class="section-header">
      <h3 class="section-title">💵 成本项目</h3>
      <el-button
        v-if="!showAddForm"
        type="success"
        size="small"
        @click="showAddForm = true"
      >
        + 添加成本项
      </el-button>
    </div>

    <!-- 成本汇总 -->
    <div class="cost-summary">
      <div class="summary-item">
        <span class="label">固定成本</span>
        <span class="value">¥{{ costSummary.fixed.toFixed(2) }}</span>
      </div>
      <div class="summary-item">
        <span class="label">按数量成本</span>
        <span class="value">¥{{ costSummary.perUnit.toFixed(2) }}/件</span>
      </div>
      <div class="summary-item">
        <span class="label">百分比成本</span>
        <span class="value">{{ costSummary.percentage }}%</span>
      </div>
    </div>
    
    <!-- 成本项目列表 - 紧凑型 -->
    <div class="cost-items-compact">
      <div
        v-for="(item, index) in costItems"
        :key="item.id"
        class="cost-item-row"
        :class="{ editing: editingCostIndex === index }"
      >
        <!-- 只读模式 -->
        <template v-if="editingCostIndex !== index">
          <div class="item-info">
            <span class="item-value">
              {{ item.cost_type === 'percentage' ? '' : '¥' }}{{ item.value }}{{ getUnit(item.cost_type) }}
            </span>
            <span class="item-name">{{ item.name }}</span>
            <el-tag :type="getTypeTagType(item.cost_type)" size="small" effect="light">
              {{ getTypeName(item.cost_type) }}
            </el-tag>
            <span v-if="item.description" class="item-desc">{{ item.description }}</span>
          </div>
          <div class="item-actions">
            <el-button type="primary" size="small" @click="startEditCostItem(index)">编辑</el-button>
            <el-button type="danger" size="small" @click="removeCostItem(index)">删除</el-button>
          </div>
        </template>

        <!-- 编辑模式 -->
        <template v-else>
          <div class="edit-mode-container">
            <!-- 标题行 -->
            <div class="edit-labels">
              <span class="label-item label-name">名称</span>
              <span class="label-item label-value">数值</span>
              <span class="label-item label-type">类型</span>
              <span class="label-item label-desc">描述</span>
              <span class="label-item label-action"></span>
            </div>
            <!-- 表单行 -->
            <div class="edit-form">
              <el-input
                v-model="item.name"
                placeholder="名称"
                size="small"
                class="edit-name"
              />
              <el-input
                v-model.number="item.value"
                type="number"
                :min="0"
                size="small"
                class="edit-value"
              >
                <template #suffix>
                  <span class="unit-suffix">{{ getUnit(item.cost_type) }}</span>
                </template>
              </el-input>
              <el-select v-model="item.cost_type" size="small" class="edit-type">
                <el-option label="固定金额" value="fixed" />
                <el-option label="按数量" value="per_unit" />
                <el-option label="百分比" value="percentage" />
              </el-select>
              <el-input
                v-model="item.description"
                placeholder="描述（可选）"
                size="small"
                class="edit-desc"
              />
              <el-button type="primary" size="small" @click="finishEditCostItem">
                完成
              </el-button>
            </div>
          </div>
        </template>
      </div>
    </div>

    <!-- 添加新成本项表单 -->
    <transition name="fade">
      <div v-if="showAddForm" class="add-cost-form">
        <div class="add-form-header">
          <span>添加新成本项</span>
          <el-button text size="small" @click="cancelAddCostItem">✕</el-button>
        </div>
        <div class="add-form-body">
          <div class="form-row">
            <div class="form-item">
              <label>名称</label>
              <el-input
                v-model="newCostItem.name"
                placeholder="如：包装费"
                size="small"
              />
            </div>
            <div class="form-item">
              <label>类型</label>
              <el-select v-model="newCostItem.cost_type" size="small" style="width: 100%">
                <el-option label="固定金额" value="fixed" />
                <el-option label="按数量计算" value="per_unit" />
                <el-option label="按百分比计算" value="percentage" />
              </el-select>
            </div>
            <div class="form-item">
              <label>数值</label>
              <el-input
                v-model.number="newCostItem.value"
                type="number"
                :min="0"
                size="small"
              >
                <template #append>{{ getUnit(newCostItem.cost_type) }}</template>
              </el-input>
            </div>
          </div>
          <div class="form-row single">
            <div class="form-item full">
              <label>描述（可选）</label>
              <el-input
                v-model="newCostItem.description"
                placeholder="简要说明此成本项的用途"
                size="small"
              />
            </div>
          </div>
          <div class="form-actions">
            <el-button size="small" @click="cancelAddCostItem">取消</el-button>
            <el-button type="primary" size="small" @click="addCostItem">确认添加</el-button>
          </div>
        </div>
      </div>
    </transition>
  </div>

  <!-- 公式说明 -->
  <div class="formula-tip">
    <p><strong>💡 智能定价公式：</strong></p>
    <code>建议价格 = 总成本 ÷ (1 - 目标毛利率)</code>
    <p class="sub-tip">总成本 = 固定成本 + (按数量成本 × 数量) + (基础成本 × 百分比成本)</p>
  </div>
</template>

<style lang="scss" scoped>
@use "./section";

// 利润率配置行
.config-row {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
  padding: 12px 20px;
  background: rgba(92, 124, 250, 0.03);
  border-radius: 10px;
}

.config-item {
  display: flex;
  align-items: center;
  gap: 12px;

  label {
    font-size: 14px;
    color: var(--text-secondary);
    white-space: nowrap;
  }
}

.config-input {
  display: flex;
  align-items: center;
  gap: 6px;

  .el-input {
    width: 90px;
  }

  .unit {
    font-size: 14px;
    color: var(--text-secondary);
    font-weight: 500;
  }
}

// 成本汇总
.cost-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
  padding: 16px 24px;
  background: linear-gradient(135deg, rgba(92, 124, 250, 0.06), rgba(156, 136, 255, 0.03));
  border-radius: 10px;
  margin-bottom: 18px;
  
  .summary-item {
    display: flex;
    flex-direction: column;
    gap: 4px;
    text-align: center;
    
    .label {
      font-size: 12px;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    
    .value {
      font-size: 18px;
      font-weight: 600;
      color: var(--text-primary);
    }
  }
}

// 成本项目列表
.cost-items-compact {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
}

.cost-item-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 20px;
  background: #fff;
  border: 1px solid rgba(92, 124, 250, 0.1);
  border-radius: 10px;
  transition: all 0.15s ease;
  min-height: 56px;
  
  &:hover {
    border-color: rgba(92, 124, 250, 0.2);
    background: rgba(92, 124, 250, 0.015);
  }
  
  &.editing {
    border-color: var(--primary-color);
    background: rgba(92, 124, 250, 0.04);
    padding: 16px 20px;
    box-shadow: 0 2px 10px rgba(92, 124, 250, 0.12);
  }
}

.item-info {
  display: flex;
  align-items: center;
  gap: 20px;
  flex: 1;
  
  .item-value {
    font-size: 16px;
    font-weight: 600;
    color: var(--primary-color);
    min-width: 70px;
  }
  
  .item-name {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
  }
  
  .item-desc {
    font-size: 13px;
    color: var(--text-secondary);
    margin-left: auto;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.item-actions {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-left: 16px;
  
  .el-button {
    padding: 6px 16px;
    font-size: 13px;
  }
}

// 编辑模式容器
.edit-mode-container {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

// 编辑表单标题行
.edit-labels {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 4px;
  
  .label-item {
    font-size: 11px;
    color: var(--text-secondary);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.3px;
  }
  
  .label-name {
    width: 100px;
  }
  
  .label-value {
    width: 90px;
  }
  
  .label-type {
    width: 110px;
  }
  
  .label-desc {
    flex: 1;
    min-width: 150px;
  }
  
  .label-action {
    width: 60px;
  }
}

// 编辑表单 - 单行布局
.edit-form {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 12px;
}

.edit-name {
  width: 100px;
  
  :deep(.el-input__inner) {
    font-size: 13px;
  }
}

.edit-type {
  width: 110px;
  
  :deep(.el-select__wrapper) {
    font-size: 13px;
  }
}

.edit-value {
  width: 90px;
  
  :deep(.el-input__inner) {
    font-size: 13px;
    text-align: center;
  }
  
  .unit-suffix {
    font-size: 12px;
    color: var(--text-secondary);
    font-weight: 500;
    margin-right: 4px;
  }
}

.edit-desc {
  flex: 1;
  min-width: 150px;
  
  :deep(.el-input__inner) {
    font-size: 13px;
  }
}

// 添加成本项表单
.add-cost-form {
  background: linear-gradient(135deg, rgba(105, 219, 124, 0.05), rgba(105, 219, 124, 0.02));
  border: 1px solid rgba(105, 219, 124, 0.2);
  border-radius: 10px;
  overflow: hidden;
  margin-bottom: 20px;
  
  .add-form-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    background: rgba(105, 219, 124, 0.06);
    font-size: 14px;
    font-weight: 500;
    color: var(--success-color);
    
    .close-btn {
      padding: 4px 8px;
      font-size: 16px;
      cursor: pointer;
      opacity: 0.6;
      
      &:hover {
        opacity: 1;
      }
    }
  }
  
  .add-form-body {
    padding: 16px 20px;
  }
  
  .form-row {
    display: flex;
    gap: 10px;
    margin-bottom: 10px;
    
    &.single {
      margin-bottom: 12px;
    }
    
    &:last-child {
      margin-bottom: 0;
    }
  }
  
  .form-item {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 3px;
    
    &.full {
      flex: 1;
    }
    
    label {
      font-size: 11px;
      color: var(--text-secondary);
      font-weight: 500;
    }
  }
  
  .form-actions {
    display: flex;
    justify-content: flex-end;
    gap: 6px;
    padding-top: 4px;
  }
}

// [未使用] 拆分前模板里就没有用到这条规则，原样保留，清理另做
// 智能定价公式区域
.pricing-formula {
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.06), rgba(255, 193, 7, 0.02));
  border: 1px solid rgba(255, 193, 7, 0.15);
  border-radius: 8px;
  padding: 12px 14px;
  margin-top: 8px;
  
  p {
    margin: 0 0 6px 0;
    font-size: 12px;
    
    &:last-child {
      margin-bottom: 0;
      font-size: 11px;
      color: var(--text-secondary);
    }
  }
  
  strong {
    color: var(--text-primary);
  }
  
  code {
    display: inline-block;
    background: rgba(92, 124, 250, 0.08);
    padding: 4px 10px;
    border-radius: 4px;
    font-family: 'SF Mono', Monaco, 'Consolas', monospace;
    font-size: 12px;
    color: var(--primary-color);
    margin: 4px 0;
  }
}

// 过渡动画
.fade-enter-active,
.fade-leave-active {
  transition: all 0.25s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}

.unit {
  font-size: 13px;
  color: var(--text-secondary);
  min-width: 20px;
}

// 公式说明
.formula-tip {
  padding: 14px 20px;
  background: linear-gradient(135deg, rgba(255, 193, 7, 0.06), rgba(255, 193, 7, 0.02));
  border: 1px solid rgba(255, 193, 7, 0.12);
  border-radius: 10px;
  font-size: 13px;
  margin-top: 16px;

  p {
    margin: 0 0 8px;
    
    &:first-child {
      margin-bottom: 10px;
    }
  }

  code {
    display: block;
    padding: 10px 14px;
    background: rgba(92, 124, 250, 0.08);
    border-radius: 6px;
    font-family: 'SF Mono', Monaco, 'Consolas', monospace;
    font-size: 13px;
    color: var(--primary-color);
    margin-bottom: 8px;
  }

  .sub-tip {
    font-size: 12px;
    color: var(--text-secondary);
    margin: 0;
  }
}
</style>
