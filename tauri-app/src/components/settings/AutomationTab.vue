<script setup lang="ts">
import { toRefs } from "vue";
import { ElMessage } from "element-plus";
import { Connection, InfoFilled, Lightning, Link, Mouse, Promotion } from "@element-plus/icons-vue";
import { useProductStore } from "@/stores/productStore";
import type { AutomationSettingsModel } from "@/composables/settings/useAutomationSettings";
import AutomationMaterialSection from "./AutomationMaterialSection.vue";
import AutomationWashLabelSection from "./AutomationWashLabelSection.vue";

// 自动化设置表单由 SettingsPanel 持有（加载 / 保存 / 未保存提示 / 保存前校验都靠它），
// 本 Tab 就地编辑；材质、水洗标两块各有自己的界面状态，拆成子区块。
const props = defineProps<{ model: AutomationSettingsModel }>();
const productStore = useProductStore();
const {
  publishMode,
  publishSubmitMode,
  capturePreferences,
  freightLoading,
  freightShopName,
  freightError,
  freightTemplates,
  shippingTemplates,
  selectedShippingTemplate,
  selectedTemplateMissing,
} = toRefs(props.model);
const { loadFreightTemplates } = props.model;

// 显示新手引导
function showOnboarding() {
  // 清除已查看标记，让引导重新显示
  localStorage.removeItem('onboarding_completed');
  // 刷新页面以显示引导
  window.location.reload();
}

// 重置引导状态
function resetOnboarding() {
  localStorage.removeItem('onboarding_completed');
  localStorage.removeItem('onboarding_completed_at');
  ElMessage.success('引导状态已重置，下次启动时将显示新手引导');
}
</script>

<template>
  <div class="settings-section">
    <h3 class="section-title">
      <el-icon class="section-icon"><Promotion /></el-icon>
      发布方式
    </h3>
    <div class="mode-card-group">
      <label
        class="mode-card"
        :class="{ active: publishMode === 'dom' }"
      >
        <input type="radio" v-model="publishMode" value="dom" />
        <el-icon class="mode-icon"><Mouse /></el-icon>
        <div class="mode-text">
          <div class="mode-name">浏览器自动发布</div>
          <div class="mode-desc">像人工一样在浏览器里逐步填表，稳定但稍慢</div>
        </div>
        <el-tag size="small" type="info" effect="plain">推荐新手</el-tag>
      </label>
      <label
        class="mode-card"
        :class="{ active: publishMode === 'protocol' }"
      >
        <input type="radio" v-model="publishMode" value="protocol" />
        <el-icon class="mode-icon"><Lightning /></el-icon>
        <div class="mode-text">
          <div class="mode-name">极速发布</div>
          <div class="mode-desc">跳过界面操作直接提交，单个商品约 18 秒</div>
        </div>
        <el-tag size="small" type="success" effect="plain">最快</el-tag>
      </label>
      <label
        class="mode-card"
        :class="{ active: publishMode === 'official' }"
      >
        <input type="radio" v-model="publishMode" value="official" />
        <el-icon class="mode-icon"><Link /></el-icon>
        <div class="mode-text">
          <div class="mode-name">抖店官方授权</div>
          <div class="mode-desc">使用抖店开放平台官方接口，最稳定，需先申请授权</div>
        </div>
        <el-tag size="small" type="warning" effect="plain">需授权</el-tag>
      </label>
    </div>
  </div>

  <div class="settings-section">
    <h3 class="section-title">
      <el-icon class="section-icon"><Promotion /></el-icon>
      提交方式
    </h3>
    <div class="capture-strategy-intro">
      决定点「开始上传」之后，商品是直接上架，还是全部填好后停下来等你检查。
    </div>
    <div class="mode-card-group">
      <label class="mode-card" :class="{ active: publishSubmitMode === 'publish' }">
        <input type="radio" v-model="publishSubmitMode" value="publish" />
        <el-icon class="mode-icon"><Promotion /></el-icon>
        <div class="mode-text">
          <div class="mode-name">直接发布</div>
          <div class="mode-desc">填完就提交上架，发布前会再确认一次</div>
        </div>
      </label>
      <label class="mode-card" :class="{ active: publishSubmitMode === 'stop' }">
        <input type="radio" v-model="publishSubmitMode" value="stop" />
        <el-icon class="mode-icon"><Mouse /></el-icon>
        <div class="mode-text">
          <div class="mode-name">只填写不发布</div>
          <div class="mode-desc">全部填好后停下，你自己核对无误再手动发布</div>
        </div>
      </label>
    </div>
  </div>

  <div class="settings-section">
    <h3 class="section-title">
      <el-icon class="section-icon"><Connection /></el-icon>
      采集方式
    </h3>
    <div class="capture-strategy-intro">
      1688 与 淘宝/天猫 是两个独立平台，采集协议互不交叉，需分别选择。
      主页粘贴链接时会按平台自动应用对应配置，无需手动切换。
    </div>
    <div class="capture-pref-list">
      <!-- 1688 -->
      <div class="capture-pref-row">
        <div class="capture-pref-platform">
          <el-icon class="strategy-icon"><Lightning /></el-icon>
          <div>
            <div class="strategy-name">1688 商品链接</div>
            <div class="strategy-host">detail.1688.com / offer.1688.com</div>
          </div>
        </div>
        <el-radio-group v-model="capturePreferences.alibaba_1688_mode" size="small">
          <el-radio-button value="dom">DOM 采集</el-radio-button>
          <el-radio-button value="protocol">协议采集</el-radio-button>
        </el-radio-group>
      </div>

      <!-- 淘宝 / 天猫 -->
      <div class="capture-pref-row">
        <div class="capture-pref-platform">
          <el-icon class="strategy-icon"><Connection /></el-icon>
          <div>
            <div class="strategy-name">淘宝 / 天猫商品链接</div>
            <div class="strategy-host">item.taobao.com / detail.tmall.com</div>
          </div>
        </div>
        <el-radio-group v-model="capturePreferences.taobao_tmall_mode" size="small">
          <el-radio-button value="dom">DOM 采集</el-radio-button>
          <el-radio-button value="protocol">协议采集</el-radio-button>
        </el-radio-group>
      </div>

      <!-- 店铺批量：无可配置项，保留说明 -->
      <div class="capture-pref-row capture-pref-row-static">
        <div class="capture-pref-platform">
          <el-icon class="strategy-icon"><Mouse /></el-icon>
          <div>
            <div class="strategy-name">淘宝 / 天猫店铺链接</div>
            <div class="strategy-host">shop*.taobao.com / *.m.tmall.com</div>
          </div>
        </div>
        <div class="capture-pref-static-tag">
          <el-tag size="small" type="info" effect="plain">浏览器批量翻页</el-tag>
          <span class="strategy-desc">店铺采集只有单一路径，无需选择</span>
        </div>
      </div>
    </div>
    <div class="capture-strategy-tip">
      <el-icon><InfoFilled /></el-icon>
      <span>
        DOM 采集 = 读浏览器渲染数据，最稳定；
        协议采集 = 拦截网络请求（预览版，目前数据提取仍会走 DOM 路径，但会把协议层网络快照保存到工件目录便于抓包分析）。
      </span>
    </div>
  </div>

  <div class="settings-section">
    <h3 class="section-title">🚚 运费模板</h3>

    <div class="freight-head">
      <span class="freight-source">
        <template v-if="freightShopName">来自店铺「{{ freightShopName }}」</template>
        <template v-else-if="freightError">{{ freightError }}</template>
        <template v-else>模板从当前登录的店铺读取</template>
      </span>
      <el-button size="small" :loading="freightLoading" :disabled="productStore.currentShopSession?.platform !== 'douyin'" @click="loadFreightTemplates(true)">
        重新读取
      </el-button>
    </div>

    <div class="current-template">
      <label>发布时使用：</label>
      <el-select
        v-model="selectedShippingTemplate"
        :disabled="productStore.currentShopSession?.platform !== 'douyin' || freightLoading"
        placeholder="选择运费模板"
        class="template-select"
      >
        <el-option
          v-for="template in shippingTemplates"
          :key="template"
          :label="template"
          :value="template"
        />
      </el-select>
    </div>

    <div v-if="selectedTemplateMissing" class="freight-missing">
      这家店没有「{{ selectedShippingTemplate }}」这个模板。发布时不会报错，但会退而选用名字相近或兜底的模板，
      运费规则可能和你以为的不一样，请从下面重新选一个。
    </div>

    <div v-if="freightTemplates.length > 0" class="template-list">
      <div
        v-for="template in freightTemplates"
        :key="template.id + template.name"
        class="template-item"
        :class="{ active: template.name === selectedShippingTemplate }"
      >
        <span class="template-name">
          <span v-if="template.name === selectedShippingTemplate" class="active-badge">✓</span>
          {{ template.name }}
          <el-tag v-if="!template.shop_scoped" size="small" type="info" effect="plain">
            平台通用
          </el-tag>
        </span>
        <el-button
          v-if="template.name !== selectedShippingTemplate"
          type="primary"
          size="small"
          class="template-use-btn"
          @click="selectedShippingTemplate = template.name"
        >
          使用
        </el-button>
      </div>
    </div>

    <AutomationMaterialSection :model="model" />

    <AutomationWashLabelSection :model="model" />
  </div>

  <!-- 配置说明 -->
  <div class="automation-tip">
    <p><strong>💡 配置说明：</strong></p>
    <ul>
      <li>📋 <strong>运费模板</strong> - 管理可用的运费模板列表，选择上传时使用的模板</li>
      <li>🧵 <strong>面料材质</strong> - 仅可选择平台材质选项，并确保总和为100%</li>
      <li>🏷️ <strong>水洗标/吊牌图</strong> - 优先使用商品目录中的吊牌图片；没有则使用这里配置的全局图片；如果两者都没有，就按上面的材质配置填写面料材质</li>
      <li>🔍 <strong>自动匹配</strong> - 脚本会在运费模板下拉列表中查找匹配的选项</li>
      <li>⚠️ <strong>注意</strong> - 模板名称需与抖音后台设置的完全一致</li>
    </ul>
  </div>

  <!-- 帮助与引导 -->
  <div class="settings-section">
    <h3 class="section-title">📚 帮助与引导</h3>
    <div class="help-buttons">
      <el-button type="primary" plain class="guide-white-btn" @click="showOnboarding">
        📖 重新查看新手引导
      </el-button>
      <el-button plain @click="resetOnboarding">
        🔄 重置引导状态
      </el-button>
    </div>
    <p class="help-tip">如果您是第一次使用本工具，建议查看新手引导了解基本操作流程。</p>
  </div>
</template>

<style lang="scss" scoped>
@use "./section";

// ========== 发布/采集方式 - 卡片单选 ==========
.mode-card-group {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mode-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  background: #fff;
  border: 1.5px solid rgba(92, 124, 250, 0.15);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast) ease;
  position: relative;

  // 隐藏原生 radio 但保留可访问性
  input[type="radio"] {
    position: absolute;
    opacity: 0;
    width: 0;
    height: 0;
  }

  &:hover {
    border-color: var(--primary-color);
    background: rgba(92, 124, 250, 0.03);
  }

  &.active {
    border-color: var(--primary-color);
    background: linear-gradient(135deg, rgba(92, 124, 250, 0.08), rgba(116, 143, 252, 0.04));
    box-shadow: 0 2px 12px rgba(92, 124, 250, 0.12);

    .mode-icon {
      color: var(--primary-color);
      transform: scale(1.05);
    }

    .mode-name {
      color: var(--primary-color);
    }
  }

  &.disabled {
    cursor: not-allowed;
    opacity: 0.55;
    background: rgba(0, 0, 0, 0.02);

    &:hover {
      border-color: rgba(92, 124, 250, 0.15);
      background: rgba(0, 0, 0, 0.02);
      box-shadow: none;
    }

    .mode-icon {
      color: var(--text-placeholder);
      transform: none;
    }

    .mode-name {
      color: var(--text-secondary);
    }
  }

  .mode-icon {
    font-size: 24px;
    color: var(--text-secondary);
    flex-shrink: 0;
    transition: all var(--transition-fast) ease;
  }

  .mode-text {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 2px;

    .mode-name {
      font-size: 14px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .mode-desc {
      font-size: 12px;
      color: var(--text-secondary);
      line-height: 1.5;
    }
  }
}

// ========== 采集策略 / 采集偏好（每平台独立可配置） ==========
.capture-strategy-intro {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 12px;
}

.capture-pref-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.capture-pref-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid rgba(92, 124, 250, 0.12);
  border-radius: var(--radius-md);
  transition: border-color var(--transition-fast) ease;

  &:hover {
    border-color: rgba(92, 124, 250, 0.25);
  }

  &.capture-pref-row-static {
    background: rgba(92, 124, 250, 0.02);
  }
}

.capture-pref-platform {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;

  .strategy-icon {
    flex-shrink: 0;
    font-size: 20px;
    color: var(--primary-color);
  }

  .strategy-name {
    font-size: 14px;
    font-weight: 600;
    color: var(--text-primary);
  }

  .strategy-host {
    font-size: 11px;
    color: var(--text-placeholder);
    font-family: "SF Mono", Consolas, monospace;
    margin-top: 2px;
  }
}

.capture-pref-static-tag {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
  text-align: right;

  .strategy-desc {
    font-size: 12px;
    color: var(--text-secondary);
  }
}

.capture-strategy-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 14px;
  background: rgba(92, 124, 250, 0.04);
  border-left: 3px solid var(--primary-color);
  border-radius: var(--radius-sm);
  font-size: 12px;
  color: var(--text-secondary);

  .el-icon {
    color: var(--primary-color);
    flex-shrink: 0;
  }
}

// 自动化设置
.current-template {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px;
  background: rgba(92, 124, 250, 0.05);
  border-radius: 8px;

  label {
    font-size: 14px;
    font-weight: 500;
    color: var(--text-primary);
    white-space: nowrap;
  }
}

.template-select {
  width: 200px;
}

.template-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.template-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: #fff;
  border: 1px solid rgba(92, 124, 250, 0.15);
  border-radius: 6px;
  transition: all 0.2s ease;

  &:hover {
    border-color: rgba(92, 124, 250, 0.3);
    background: rgba(92, 124, 250, 0.02);
  }

  &.active {
    border-color: var(--primary-color);
    background: rgba(92, 124, 250, 0.05);
  }
}

.template-name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--text-primary);
}

.active-badge {
  color: var(--success-color);
  font-weight: bold;
}

// [未使用] 拆分前模板里就没有用到这条规则，原样保留，清理另做
.template-actions {
  display: flex;
  gap: 4px;
}

.template-use-btn {
  // 强制保证文字始终白色，避免被全局 el-button text 默认色或主题色覆盖
  color: #fff !important;
}

.freight-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.freight-source {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.freight-missing {
  margin: 10px 0;
  padding: 8px 12px;
  border-radius: var(--radius-sm);
  background: rgba(217, 130, 43, 0.1);
  font-size: var(--font-size-xs);
  line-height: 1.6;
  color: #9a5b00;
}

// [未使用] 拆分前模板里就没有用到这条规则，原样保留，清理另做
.add-template-form {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: rgba(105, 219, 124, 0.05);
  border: 1px dashed rgba(105, 219, 124, 0.4);
  border-radius: 8px;
}

// [未使用] 拆分前模板里就没有用到这条规则，原样保留，清理另做
.template-input {
  flex: 1;
  max-width: 300px;
}

.automation-tip {
  padding: 12px 16px;
  background: rgba(92, 124, 250, 0.05);
  border-radius: 8px;
  font-size: 13px;
  margin-top: 20px;

  p {
    margin: 0 0 8px;
  }

  ul {
    margin: 0;
    padding-left: 20px;
  }

  li {
    margin-bottom: 4px;
  }
}

// 帮助与引导
.help-buttons {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.guide-white-btn {
  --el-button-text-color: #fff;
  --el-button-hover-text-color: #fff;
  --el-button-active-text-color: #fff;
}

.help-tip {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}
</style>
