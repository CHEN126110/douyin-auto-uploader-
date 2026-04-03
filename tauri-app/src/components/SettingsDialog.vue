<script setup lang="ts">
import SettingsPanel from "@/components/SettingsPanel.vue";

defineProps<{
  visible: boolean;
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
}>();

function handleClose() {
  emit("update:visible", false);
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    width="1200px"
    top="5vh"
    class="settings-dialog"
    :lock-scroll="false"
    :close-on-click-modal="false"
    @close="handleClose"
  >
    <template #header>
      <div class="dialog-header">
        <span class="dialog-title">系统设置</span>
      </div>
    </template>

    <SettingsPanel
      v-if="visible"
      mode="dialog"
      :show-close-button="true"
      :close-on-save="true"
      close-button-text="取消"
      @close="handleClose"
    />
  </el-dialog>
</template>

<style lang="scss" scoped>
:deep(.el-dialog) {
  max-height: 90vh;
  margin: 0 auto !important;
}

:deep(.el-dialog__body) {
  overflow: visible;
  padding: 0 20px 20px;
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.dialog-title {
  font-size: 18px;
  font-weight: 600;
}
</style>
