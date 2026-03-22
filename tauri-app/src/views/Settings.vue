<script setup lang="ts">
// 独立设置页面 - 预留给未来扩展
import { useRouter } from "vue-router";

const router = useRouter();

function goBack() {
  router.push("/");
}
</script>

<template>
  <div class="settings-page">
    <div class="page-header">
      <el-button @click="goBack">← 返回</el-button>
      <h1>系统设置</h1>
    </div>

    <div class="settings-container">
      <p>设置页面 - 待实现</p>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.settings-page {
  padding: var(--container-padding);
  min-height: 100vh;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;

  h1 {
    margin: 0;
    font-size: var(--font-size-title);
    color: var(--text-primary);
  }
}

.settings-container {
  background: var(--card-background);
  border-radius: var(--radius-lg);
  padding: var(--container-padding);
  box-shadow: var(--shadow-lg);
}
</style>
