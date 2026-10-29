<script setup lang="ts">
import { computed, ref, toRefs } from "vue";
import { ElMessage } from "element-plus";
import { Warning } from "@element-plus/icons-vue";
import type { AutomationSettingsModel } from "@/composables/settings/useAutomationSettings";

// 材质含量由 SettingsPanel 持有（保存前要校验含量合计），本区块就地编辑；
// 「新增材质」的输入框等界面状态留在这里。
const props = defineProps<{ model: AutomationSettingsModel }>();
const { materialOptions, materialCompositions, materialPercentageTotal, materialSettingsInvalid } = toRefs(props.model);

const newMaterialName = ref("");
const newMaterialPercentage = ref(0);

/** 该材质是否为平台选项之外的自定义项（仅用于提示，不阻断保存） */
function isCustomMaterial(name: string): boolean {
  const value = String(name || "").trim();
  if (!value) return false;
  return !materialOptions.value.includes(value);
}

const customMaterialNames = computed(() =>
  materialCompositions.value
    .map((item) => String(item.material || "").trim())
    .filter((name) => name && isCustomMaterial(name))
);

function addMaterialComposition() {
  const material = newMaterialName.value.trim();
  const percentage = Number(newMaterialPercentage.value);
  if (!material) {
    ElMessage.warning("请选择或输入材质");
    return;
  }
  if (materialCompositions.value.some((item) => item.material === material)) {
    ElMessage.warning("该材质已存在");
    return;
  }
  if (!Number.isFinite(percentage) || percentage <= 0) {
    ElMessage.warning("请输入有效含量");
    return;
  }
  materialCompositions.value.push({ material, percentage });
  newMaterialName.value = "";
  newMaterialPercentage.value = 0;
}

function removeMaterialComposition(index: number) {
  materialCompositions.value.splice(index, 1);
}
</script>

<template>
  <h3 class="section-title material-title">🧵 产品材质面料（默认）</h3>
  <div class="material-config-panel" :class="{ invalid: materialSettingsInvalid }">
    <div class="material-custom-text">
      仅在没有商品成分资料时使用；商品有完整成分时按实际填写，不完整或冲突时会停止发布，不会用此处默认值凑足 100%。
    </div>
    <div class="material-list">
      <div
        v-for="(item, index) in materialCompositions"
        :key="`material-${index}`"
        class="material-item"
      >
        <el-select
          v-model="item.material"
          placeholder="选择或输入材质"
          filterable
          allow-create
          default-first-option
          :reserve-keyword="false"
          class="material-name-input"
        >
          <el-option
            v-for="option in materialOptions"
            :key="`material-option-${option}`"
            :label="option"
            :value="option"
          />
        </el-select>
        <el-input-number
          v-model="item.percentage"
          :min="0.01"
          :max="100"
          :precision="2"
          :controls="false"
          class="material-percentage-input"
        />
        <span class="material-unit">%</span>
        <el-button
          type="danger"
          size="small"
          class="automation-delete-btn"
          :disabled="materialCompositions.length <= 1"
          @click="removeMaterialComposition(index)"
        >
          删除
        </el-button>
      </div>
    </div>
    <div class="add-material-form">
      <el-select
        v-model="newMaterialName"
        placeholder="选择或输入材质"
        filterable
        allow-create
        default-first-option
        :reserve-keyword="false"
        class="material-name-input"
      >
        <el-option
          v-for="option in materialOptions"
          :key="`new-material-option-${option}`"
          :label="option"
          :value="option"
        />
      </el-select>
      <el-input-number
        v-model="newMaterialPercentage"
        :min="0.01"
        :max="100"
        :precision="2"
        :controls="false"
        class="material-percentage-input"
      />
      <span class="material-unit">%</span>
      <el-button type="primary" @click="addMaterialComposition">
        添加材质
      </el-button>
    </div>
    <div class="material-total-row">
      <div class="material-total-label">
        <span>含量总和</span>
        <span
          class="material-total-value"
          :class="{ warning: materialPercentageTotal !== 100 }"
        >
          {{ materialPercentageTotal }}%
        </span>
        <span class="material-total-target">/ 100%</span>
      </div>
      <el-progress
        :percentage="Math.min(materialPercentageTotal, 100)"
        :status="materialPercentageTotal === 100 ? 'success' : (materialPercentageTotal > 100 ? 'exception' : undefined)"
        :stroke-width="8"
        :show-text="false"
        class="material-progress"
      />
    </div>
    <div v-if="materialSettingsInvalid" class="material-warning-text">
      <el-icon><Warning /></el-icon>
      <span>材质名称不能为空，且含量总和必须等于 100%</span>
    </div>
    <div v-else-if="customMaterialNames.length" class="material-custom-text">
      <el-icon><Warning /></el-icon>
      <span>
        自定义材质：{{ customMaterialNames.join("、") }}
        —— 不在已知平台选项内，发布时若平台下拉搜不到该材质会报错，请确认名称与平台一致
      </span>
    </div>
  </div>
</template>

<style lang="scss" scoped>
@use "./section";

.material-title {
  margin-top: 20px;
}

.material-config-panel {
  padding: 12px;
  border: 1px solid rgba(92, 124, 250, 0.2);
  border-radius: 10px;
  background: rgba(92, 124, 250, 0.03);
}

.material-config-panel.invalid {
  border-color: var(--danger-color);
  box-shadow: 0 0 0 1px rgba(245, 108, 108, 0.25) inset;
}

.material-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.material-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: 1px solid rgba(92, 124, 250, 0.15);
  border-radius: 8px;
  background: rgba(92, 124, 250, 0.02);
}

.material-name-input {
  width: 240px;
}

.material-percentage-input {
  width: 120px;
}

.material-unit {
  font-size: 13px;
  color: var(--text-secondary);
}

.add-material-form {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  border: 1px dashed rgba(105, 219, 124, 0.4);
  border-radius: 8px;
  background: rgba(105, 219, 124, 0.05);
}

// [未使用] 拆分前模板里就没有用到这条规则，原样保留，清理另做
.material-total {
  margin-top: 10px;
  font-size: 13px;
  color: var(--text-secondary);
}

// [未使用] 拆分前模板里就没有用到这条规则，原样保留，清理另做
.material-total.warning {
  color: var(--danger-color);
}

.material-warning-text {
  margin-top: 8px;
  font-size: 12px;
  color: var(--danger-color);
}

// ========== 材质含量进度 ==========
.material-total-row {
  margin-top: 12px;
}

.material-total-label {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 6px;

  .material-total-value {
    font-size: 16px;
    font-weight: 700;
    color: var(--success-color);

    &.warning {
      color: var(--danger-color);
    }
  }

  .material-total-target {
    font-size: 12px;
    color: var(--text-placeholder);
  }
}

.material-progress {
  width: 100%;
}

.material-custom-text {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 12px;
  background: rgba(230, 162, 60, 0.08);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--el-color-warning, #e6a23c);
  line-height: 1.5;

  .el-icon {
    flex-shrink: 0;
    font-size: 14px;
  }
}

.material-warning-text {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding: 6px 12px;
  background: rgba(255, 138, 128, 0.08);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--danger-color);

  .el-icon {
    font-size: 14px;
  }
}

.automation-delete-btn {
  color: #fff !important;
}
</style>
