<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import SettingsPanel from "@/components/SettingsPanel.vue";

const router = useRouter();
const route = useRoute();

const pageTitle = computed(() => {
  const tab = route.query.tab;
  if (tab === "automation") {
    return "自动化设置";
  }
  return "系统设置";
});

function goBack() {
  router.push("/");
}
</script>

<template>
  <div class="settings-page">
    <div class="page-header">
      <div class="header-left">
        <el-button @click="goBack">返回</el-button>
        <div class="header-text">
          <h1>{{ pageTitle }}</h1>
          <p>设置内容已迁移为独立页面，保存逻辑与原弹窗保持一致。</p>
        </div>
      </div>
    </div>

    <SettingsPanel mode="page" />
  </div>
</template>

<style lang="scss" scoped>
.settings-page {
  padding: var(--container-padding);
  min-height: 100vh;
  background: var(--background-color);
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
}

.header-text {
  display: flex;
  flex-direction: column;
  gap: 4px;

  h1 {
    margin: 0;
    font-size: var(--font-size-title);
    color: var(--text-primary);
  }

  p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 14px;
  }
}
</style>
