<script setup lang="ts">
import { computed, ref, toRefs } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/services/api";
import type { AutomationSettingsModel } from "@/composables/settings/useAutomationSettings";

// 水洗标图片路径由 SettingsPanel 持有（要随设置一起保存），本区块负责选择 / 清空。
const props = defineProps<{ model: AutomationSettingsModel }>();
const { washLabelTagImagePath } = toRefs(props.model);

const washLabelTagImageLoading = ref(false);
const washLabelTagImagePreviewUrl = computed(() => {
  const p = washLabelTagImagePath.value.trim();
  if (!p) return "";
  return api.automationWashLabelPreviewUrl();
});

async function selectWashLabelTagImage() {
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      directory: false,
      multiple: false,
      title: "选择水洗标/吊牌图",
      filters: [
        {
          name: "图片文件",
          extensions: ["jpg", "jpeg", "png", "bmp", "webp"],
        },
      ],
    });

    if (!selected || Array.isArray(selected)) {
      return;
    }

    washLabelTagImageLoading.value = true;
    const response = await api.importAutomationWashLabelTagImage(String(selected));
    if (response.success && response.data?.stored_path) {
      washLabelTagImagePath.value = response.data.stored_path;
      ElMessage.success(response.msg || "水洗标/吊牌图导入成功");
      return;
    }
    ElMessage.error(response.msg || "水洗标/吊牌图导入失败");
  } catch (error) {
    console.error("选择水洗标/吊牌图失败:", error);
    ElMessage.error("无法选择水洗标/吊牌图");
  } finally {
    washLabelTagImageLoading.value = false;
  }
}

async function clearWashLabelTagImage() {
  if (!washLabelTagImagePath.value) {
    return;
  }
  try {
    await ElMessageBox.confirm("确定清空当前水洗标/吊牌图吗？", "提示", {
      type: "warning",
    });
    washLabelTagImageLoading.value = true;
    const response = await api.removeAutomationWashLabelTagImage(washLabelTagImagePath.value);
    if (!response.success) {
      ElMessage.error(response.msg || "清空水洗标/吊牌图失败");
      return;
    }
    washLabelTagImagePath.value = "";
    ElMessage.success(response.msg || "水洗标/吊牌图已清空");
  } catch (error) {
    if (error !== "cancel") {
      console.error("清空水洗标/吊牌图失败:", error);
    }
  } finally {
    washLabelTagImageLoading.value = false;
  }
}
</script>

<template>
  <h3 class="section-title certificate-title">🏷️ 水洗标/吊牌图</h3>
  <div class="certificate-config-panel">
    <div class="certificate-file-info">
      <template v-if="washLabelTagImagePath">
        <img
          :src="washLabelTagImagePreviewUrl"
          class="certificate-preview-img"
          alt="水洗标/吊牌图"
        />
      </template>
      <div v-else class="certificate-empty-tip">
        当前未配置水洗标/吊牌图。发布页出现“水洗标/吊牌图”必填项时，自动化会优先上传商品目录中的吊牌图片；若商品目录没有，则使用这里配置的全局图片。
      </div>
    </div>
    <div class="certificate-actions">
      <el-button
        type="primary"
        :loading="washLabelTagImageLoading"
        @click="selectWashLabelTagImage"
      >
        {{ washLabelTagImagePath ? "重新选择图片" : "选择水洗标/吊牌图" }}
      </el-button>
      <el-button
        :disabled="!washLabelTagImagePath || washLabelTagImageLoading"
        @click="clearWashLabelTagImage"
      >
        清空图片
      </el-button>
    </div>
  </div>
</template>

<style lang="scss" scoped>
@use "./section";

.certificate-title {
  margin-top: 20px;
}

.certificate-config-panel {
  padding: 14px;
  border: 1px solid rgba(92, 124, 250, 0.2);
  border-radius: 10px;
  background: rgba(92, 124, 250, 0.03);
}

.certificate-file-info {
  margin-bottom: 12px;
}

.certificate-preview-img {
  max-width: 200px;
  max-height: 160px;
  object-fit: contain;
  border-radius: 8px;
  border: 1px solid rgba(92, 124, 250, 0.15);
  background: #fff;
  padding: 4px;
}

.certificate-empty-tip {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.certificate-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
