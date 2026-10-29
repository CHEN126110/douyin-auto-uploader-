<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ElMessage } from "element-plus";
import { CircleCheck, Promotion, Warning } from "@element-plus/icons-vue";
import { api } from "@/services/api";
import { usePricingSettings } from "@/composables/settings/usePricingSettings";
import { useModelSettings } from "@/composables/settings/useModelSettings";
import { useAutomationSettings } from "@/composables/settings/useAutomationSettings";
import PricingTab from "@/components/settings/PricingTab.vue";
import ModelTab from "@/components/settings/ModelTab.vue";
import AutomationTab from "@/components/settings/AutomationTab.vue";
import McpTab from "@/components/settings/McpTab.vue";
import AboutTab from "@/components/settings/AboutTab.vue";
import type { Settings } from "@/types";

/**
 * 设置面板外壳：标签页容器 + 底部保存栏 + 「加载 / 保存 / 未保存提示」的统一编排。
 *
 * 各 Tab 的界面在 components/settings/ 下，表单数据由下面三个模型持有
 * （价格 / 模型 / 自动化），Tab 通过 props 拿到同一个对象就地编辑；
 * 「高级集成」「关于」是只读页，数据自己持有，不参与保存。
 */

// 当前选中的标签页
type SettingsTab = "pricing" | "model" | "automation" | "mcp";

const SETTINGS_TABS: SettingsTab[] = ["pricing", "model", "automation", "mcp"];
const route = useRoute();
const routeTab = typeof route.query.tab === "string" ? route.query.tab : "";
const activeTab = ref<SettingsTab>(
  SETTINGS_TABS.includes(routeTab as SettingsTab) ? (routeTab as SettingsTab) : "pricing"
);

// 各 Tab 共用同一个滚动容器（.settings-content 里的 .el-tabs__content）。
// 切换 Tab 时一律回到顶部。实测：拆分前从左往右切 Tab 总是从头开始；
// 拆分后如果不处理，浏览器只会把滚动位置截断到新内容的高度——
// 在长 Tab 里滚下去、切到短 Tab 再切回来，新 Tab 会停在半截，开头被顶出屏幕。
const tabsBodyRef = ref<HTMLElement | null>(null);
watch(
  activeTab,
  () => {
    const scroller = tabsBodyRef.value?.querySelector<HTMLElement>(".el-tabs__content");
    if (scroller) scroller.scrollTop = 0;
  },
  { flush: "post" }
);

// 加载状态
const loading = ref(false);

// 是否有未保存的更改
const hasUnsavedChanges = ref(false);
// 初次 loadSettings 完成前，所有 watch 都不应标记为 dirty
const settingsLoaded = ref(false);

function markDirty() {
  if (settingsLoaded.value) {
    hasUnsavedChanges.value = true;
  }
}

// 设置加载失败标记。加载失败时面板显示的是各表单模型里的硬编码默认值，
// 一旦保存就会把后端真实的成本项 / 运费模板 / 材质成分 / 洗唛吊牌图 / 发布模式 /
// 采集偏好整体覆盖，所以必须禁用保存并把失败原因暴露给用户。
const loadFailed = ref(false);
// 原始错误信息，直接展示给用户作为排查入口，不做吞掉或美化
const loadErrorMessage = ref("");

function markLoadFailed(detail: string) {
  loadFailed.value = true;
  loadErrorMessage.value = detail;
  ElMessage.error(`设置加载失败：${detail}。请确认后端已启动，修复后点击「重试加载」，在此之前请勿保存`);
}

// ========== 三份表单模型 ==========

const pricing = usePricingSettings();
const models = useModelSettings();
const automation = useAutomationSettings();

// ========== 保存和加载 ==========

// 加载所有设置
async function loadSettings() {
  loading.value = true;
  try {
    const response = await api.getSettings();

    if (response.success && response.data?.settings) {
      const settings = response.data.settings as Settings;

      // 加载价格配置、成本项目
      pricing.applySettings(settings);

      // 加载模型配置
      models.applySettings(settings);

      // 加载自动化配置
      automation.applySettings(settings);

      // 只有真正拿到后端设置才允许保存
      loadFailed.value = false;
      loadErrorMessage.value = "";
    } else {
      // 后端返回 success:false 或缺少 settings：界面上留下的是各表单模型里的硬编码默认值，
      // 此时保存会把后端真实的 cost_items / shipping_templates / material_compositions /
      // wash_label_tag_image_path / publish_mode / capture_preferences 整体覆盖掉。
      const detail =
        (response as { msg?: string; message?: string }).msg ||
        (response as { msg?: string; message?: string }).message ||
        "后端未返回设置数据";
      console.error("加载设置失败:", response);
      markLoadFailed(detail);
    }
  } catch (error) {
    console.error("加载设置失败:", error);
    markLoadFailed(error instanceof Error ? error.message : String(error));
  } finally {
    loading.value = false;
    // 先让本次 loadSettings 赋值触发的 watch 回调（默认 'pre' flush，下一 tick 才执行）
    // 在 settingsLoaded 仍为 false 时跑完。否则这些"加载赋值"会在下一 tick 被 markDirty
    // 误判为用户改动，导致设置页一加载就显示"有未保存的更改"。
    await nextTick();
    settingsLoaded.value = true;
    hasUnsavedChanges.value = false;
  }
}

// 保存所有设置
async function handleSave() {
  loading.value = true;
  try {
    // 后端期望百分比形式（如30），直接发送输入框的值
    const settingsToSave: Settings = {
      ...pricing.buildPayload(),
      model_configs: models.modelConfigs,
      automation_config: automation.buildPayload(),
    };

    if (automation.materialSettingsInvalid) {
      activeTab.value = "automation";
      ElMessage.warning("材质名称不能为空，且含量总和必须等于100%");
      loading.value = false;
      return;
    }

    // 注意：这里不要打印 settingsToSave —— model_configs[].api_key 是明文密钥，
    // 控制台日志在打包版同样保留（vite.config.ts 没开 drop_console）。
    const response = await api.updateSettings(settingsToSave);

    if (response.success) {
      ElMessage.success("设置保存成功");
      hasUnsavedChanges.value = false;
    } else {
      ElMessage.error(response.msg || "保存失败");
    }
  } catch (error) {
    console.error("保存设置失败:", error);
    ElMessage.error("保存失败");
  } finally {
    loading.value = false;
  }
}

// 监听用户改动，统一标记 dirty。
// 只放用户在界面上能改的字段。automation.shippingTemplates（运费模板名单）不在此列：
// 它是从店铺读回来的缓存，界面上没有增删入口，程序读店铺时改写它不是用户改动；
// 放进来的话，设置页一打开（读店铺会重新赋值）就会被标成「有未保存的更改」。
watch(
  [
    () => pricing.pricingConfig,
    () => pricing.costItems,
    () => models.modelConfigs,
    () => automation.selectedShippingTemplate,
    () => automation.materialCompositions,
    () => automation.washLabelTagImagePath,
    () => automation.publishMode,
    () => automation.publishSubmitMode,
    () => automation.capturePreferences.alibaba_1688_mode,
    () => automation.capturePreferences.taobao_tmall_mode,
  ],
  () => {
    markDirty();
  },
  { deep: true }
);

// 初始化设置页面
onMounted(async () => {
  await loadSettings();
  // 运费模板每次打开设置都重新读：换过店铺的话，上次那批是别人家的。
  void automation.loadFreightTemplates();
});
</script>

<template>
  <div class="settings-panel">
    <div ref="tabsBodyRef" v-loading="loading" class="settings-content">
      <el-tabs v-model="activeTab" class="settings-tabs">
        <!-- 价格设置标签页 -->
        <el-tab-pane label="💰 价格设置" name="pricing">
          <PricingTab :model="pricing" />
        </el-tab-pane>

        <!-- 智能模型 -->
        <el-tab-pane label="🤖 智能模型" name="model">
          <ModelTab :model="models" />
        </el-tab-pane>

        <!-- 自动化设置标签页 -->
        <el-tab-pane label="🤖 自动化设置" name="automation">
          <AutomationTab :model="automation" />
        </el-tab-pane>

        <el-tab-pane label="🧩 高级集成" name="mcp">
          <McpTab />
        </el-tab-pane>

        <el-tab-pane label="ℹ️ 关于" name="about">
          <AboutTab />
        </el-tab-pane>
      </el-tabs>
    </div>
    <div class="settings-footer">
      <div class="footer-status">
        <template v-if="loadFailed">
          <el-icon class="status-icon failed"><Warning /></el-icon>
          <span class="status-text failed">设置加载失败，已禁用保存（当前显示的是默认值，保存会覆盖后端真实配置）</span>
          <span v-if="loadErrorMessage" class="status-error-detail" :title="loadErrorMessage">
            {{ loadErrorMessage }}
          </span>
          <el-button size="small" :loading="loading" @click="loadSettings">重试加载</el-button>
        </template>
        <template v-else-if="hasUnsavedChanges">
          <el-icon class="status-icon dirty"><Warning /></el-icon>
          <span class="status-text dirty">有未保存的更改</span>
        </template>
        <template v-else>
          <el-icon class="status-icon clean"><CircleCheck /></el-icon>
          <span class="status-text clean">所有更改已保存</span>
        </template>
      </div>
      <div class="footer-actions">
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          :disabled="loadFailed || (!hasUnsavedChanges && !loading)"
          @click="handleSave"
        >
          <el-icon><Promotion /></el-icon>
          <span style="margin-left: 6px">保存设置</span>
        </el-button>
      </div>
    </div>
  </div>
</template>

<style lang="scss" scoped>
.settings-panel {
  background: var(--card-background);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: 20px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.settings-content {
  flex: 1;
  min-height: 0;
  // 滚动下放到 .el-tabs__content：让 tab 标签栏完全脱离滚动区域
  overflow: hidden;
  padding: 0;
  display: flex;
  flex-direction: column;
}

.settings-tabs {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;

  // Tab 头：在滚动区域之外，自然固定在顶部，不会有滚动条穿过
  :deep(.el-tabs__header) {
    flex-shrink: 0;
    margin: 0 0 16px 0;
    padding: 0 20px 0 10px;
    background: var(--card-background-solid);
    border-bottom: 1px solid rgba(92, 124, 250, 0.1);
  }

  // Tab 内容区：真正的滚动容器，滚动条只出现在这里
  :deep(.el-tabs__content) {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
    // 底部留出 32px 呼吸空间，避免滚到底时最后一行紧贴 footer 看起来被截
    padding: 0 20px 32px 10px;
  }

  :deep(.el-tab-pane) {
    height: auto;
  }

  :deep(.el-tabs__item) {
    font-size: 15px;
    padding: 0 24px;
  }
}

// ========== Sticky 底部保存栏 ==========
.settings-footer {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 14px 24px;
  margin: 16px -20px -20px;
  background: rgba(255, 255, 255, 0.96);
  border-top: 1px solid rgba(92, 124, 250, 0.12);
  backdrop-filter: blur(8px);
  position: sticky;
  bottom: 0;
  z-index: 5;
}

.footer-status {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;

  .status-icon {
    font-size: 16px;

    &.dirty {
      color: var(--warning-light);
    }

    &.clean {
      color: var(--success-color);
    }

    &.failed {
      color: var(--danger-color);
    }
  }

  .status-text {
    &.dirty {
      color: var(--warning-light);
      font-weight: 500;
    }

    &.clean {
      color: var(--text-secondary);
    }

    &.failed {
      color: var(--danger-color);
      font-weight: 500;
    }
  }

  .status-error-detail {
    max-width: 340px;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    font-size: 12px;
    color: var(--text-secondary);
  }
}

.footer-actions {
  display: flex;
  gap: 12px;
}

// ========== 设置面板自身的滚动布局调整 ==========
.settings-panel {
  position: relative;
}
</style>
