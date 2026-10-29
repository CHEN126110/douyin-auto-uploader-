<script setup lang="ts">
import { onMounted, ref } from "vue";
import { InfoFilled } from "@element-plus/icons-vue";
import { getVersion } from "@tauri-apps/api/app";
import { checkForUpdate } from "@/services/updater";

// 应用版本（来自 tauri.conf.json，与自动更新比对的是同一个权威版本号）
const appVersion = ref<string>("");
const checkingUpdate = ref<boolean>(false);

async function handleCheckUpdate() {
  checkingUpdate.value = true;
  try {
    await checkForUpdate();
  } finally {
    checkingUpdate.value = false;
  }
}

onMounted(async () => {
  try {
    appVersion.value = await getVersion();
  } catch {
    appVersion.value = "";
  }
});
</script>

<template>
  <div class="settings-section">
    <h3 class="section-title">
      <el-icon class="section-icon"><InfoFilled /></el-icon>
      关于与更新
    </h3>
    <div class="mcp-env-grid">
      <div class="mcp-env-item">
        <div class="env-label">当前版本</div>
        <div class="env-value">
          <el-tag size="small" type="success">v{{ appVersion || "—" }}</el-tag>
        </div>
      </div>
      <div class="mcp-env-item">
        <div class="env-label">软件更新</div>
        <div class="env-value">
          <el-button
            type="primary"
            size="small"
            :loading="checkingUpdate"
            @click="handleCheckUpdate"
          >
            {{ checkingUpdate ? "检查中" : "检查更新" }}
          </el-button>
        </div>
      </div>
    </div>
    <div class="mcp-hint">
      <el-icon><InfoFilled /></el-icon>
      <span>点击「检查更新」会从官方发布源获取最新版本；有新版时可一键下载并自动安装、重启。更新为整包下载（含后端，体积较大），更新前请先确保没有正在进行的采集 / 发布任务。</span>
    </div>
  </div>
</template>

<style lang="scss" scoped>
@use "./section";
@use "./info-grid";
</style>
