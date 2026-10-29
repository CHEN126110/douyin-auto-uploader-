<script setup lang="ts">
import { ref, toRefs } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { api } from "@/services/api";
import type { ModelConfig } from "@/types";
import {
  applyModelProviderDefaults,
  createNewModelConfig,
  type ModelSettingsModel,
} from "@/composables/settings/useModelSettings";

// 模型配置列表由 SettingsPanel 持有（加载 / 保存 / 未保存提示都靠它），本 Tab 就地编辑。
const props = defineProps<{ model: ModelSettingsModel }>();
const { modelConfigs } = toRefs(props.model);

// 新增模型配置
const newModelConfig = ref<ModelConfig>(createNewModelConfig());

function handleModelProviderChange(config: ModelConfig): void {
  applyModelProviderDefaults(config);
}

// 添加模型配置
function addModelConfig() {
  if (!newModelConfig.value.name.trim()) {
    ElMessage.warning("请输入配置名称");
    return;
  }

  modelConfigs.value.push({
    ...newModelConfig.value,
    id: Date.now().toString(),
  });

  // 重置表单
  newModelConfig.value = createNewModelConfig();

  ElMessage.success("添加成功");
}

// 删除模型配置
async function removeModelConfig(index: number) {
  try {
    await ElMessageBox.confirm("确定删除该模型配置吗？", "提示", {
      type: "warning",
    });
    modelConfigs.value.splice(index, 1);
    ElMessage.success("删除成功");
  } catch {
    // 用户取消
  }
}

// 服务商 → 后端能识别的 provider 名映射。后端 /api/ai/test 支持 deepseek / xiaomi。
const TESTABLE_PROVIDER_MAP: Record<string, string> = {
  deepseek: "deepseek",
  xiaomi: "xiaomi",
};

const testingModelId = ref<string>("");
const fetchingModelsId = ref<string>("");
const modelOptions = ref<Record<string, string[]>>({});

// 通过官方 GET /models 动态获取模型列表（避免手输错误、自动跟进最新模型）
async function fetchModels(config: ModelConfig) {
  const apiKey = String(config.api_key || "").trim();
  const apiBase = String(config.api_base || "").trim();
  if (!apiKey) {
    ElMessage.warning("请先填写访问密钥后再获取模型");
    return;
  }
  if (!apiBase) {
    ElMessage.warning("请先填写服务地址后再获取模型");
    return;
  }
  fetchingModelsId.value = config.id;
  try {
    const resp = await api.listAiModels({
      provider: config.provider,
      api_key: apiKey,
      api_base: apiBase,
    });
    const models = resp?.data?.models || [];
    if (models.length) {
      modelOptions.value = { ...modelOptions.value, [config.id]: models };
      if (!config.model_name || !models.includes(config.model_name)) {
        config.model_name = models[0];
      }
      ElMessage.success(`获取到 ${models.length} 个模型`);
    } else {
      ElMessage.warning("未获取到模型列表");
    }
  } catch (error: any) {
    const detail = error?.response?.data?.msg || error?.message || String(error);
    ElMessage.error(`获取模型失败：${detail}`);
  } finally {
    fetchingModelsId.value = "";
  }
}

async function testModelConnection(config: ModelConfig) {
  const providerKey = String(config.provider || "").trim();
  const backendProvider = TESTABLE_PROVIDER_MAP[providerKey];

  if (!backendProvider) {
    ElMessage.warning(
      `「${providerKey || "未指定服务商"}」暂不支持一键测试，请先保存后手动验证一次`
    );
    return;
  }

  const apiKey = String(config.api_key || "").trim();
  if (!apiKey) {
    ElMessage.warning("请先填写访问密钥后再测试连接");
    return;
  }
  const apiBase = String(config.api_base || "").trim();
  if (!apiBase) {
    ElMessage.warning("请先填写服务地址（base_url）后再测试连接");
    return;
  }

  testingModelId.value = config.id;
  try {
    const payload = {
      [backendProvider]: {
        enabled: true,
        api_key: apiKey,
        model: String(config.model_name || "").trim(),
        api_base: apiBase,
      },
    };
    const response = await api.testAiConfig(payload);
    const result = response?.data?.[backendProvider];

    if (result?.success) {
      ElMessage.success(`${config.name} 连接成功`);
    } else {
      const reason = result?.error || response?.msg || "未知原因";
      ElMessage.error(`${config.name} 连接失败：${reason}`);
    }
  } catch (error: any) {
    console.error("测试模型连接失败:", error);
    const detail = error?.response?.data?.msg || error?.message || String(error);
    ElMessage.error(`${config.name} 连接失败：${detail}`);
  } finally {
    testingModelId.value = "";
  }
}
</script>

<template>
  <div class="settings-section">
    <h3 class="section-title">🔗 已配置的模型</h3>
    
    <div class="model-configs-list">
      <div
        v-for="(config, index) in modelConfigs"
        :key="config.id"
        class="model-config-item"
      >
        <div class="model-header">
          <div class="model-info">
            <span class="model-name">{{ config.name }}</span>
            <el-tag size="small" :type="config.enabled ? 'success' : 'info'">
              {{ config.enabled ? '已启用' : '未启用' }}
            </el-tag>
          </div>
          <div class="model-actions">
            <el-switch v-model="config.enabled" size="small" />
            <el-button
              size="small"
              :loading="testingModelId === config.id"
              @click="testModelConnection(config)"
            >
              {{ testingModelId === config.id ? '测试中' : '测试' }}
            </el-button>
            <el-button
              type="danger"
              size="small"
              @click="removeModelConfig(index)"
            >
              删除
            </el-button>
          </div>
        </div>
        
        <div class="model-details">
          <div class="detail-row">
            <label>服务商</label>
            <el-select
              v-model="config.provider"
              size="small"
              @change="handleModelProviderChange(config)"
            >
              <el-option label="DeepSeek" value="deepseek" />
              <el-option label="小米大模型" value="xiaomi" />
            </el-select>
          </div>
          <div class="detail-row">
            <label>服务地址</label>
            <el-input
              v-model="config.api_base"
              placeholder="服务地址，如 https://api.openai.com/v1"
              size="small"
            />
          </div>
          <div class="detail-row">
            <label>访问密钥</label>
            <el-input
              v-model="config.api_key"
              type="password"
              placeholder="填入服务商提供的访问密钥；本地模型可留空"
              size="small"
              show-password
            />
          </div>
          <div class="detail-row">
            <label>模型名称</label>
            <div style="display:flex; gap:8px; flex:1; align-items:center;">
              <el-select
                v-model="config.model_name"
                size="small"
                filterable
                allow-create
                default-first-option
                placeholder="点右侧『获取模型』，或手动输入"
                style="flex:1;"
              >
                <el-option
                  v-for="m in (modelOptions[config.id] || [])"
                  :key="m"
                  :label="m"
                  :value="m"
                />
              </el-select>
              <el-button
                size="small"
                :loading="fetchingModelsId === config.id"
                @click="fetchModels(config)"
              >
                {{ fetchingModelsId === config.id ? '获取中' : '获取模型' }}
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加新模型配置 -->
    <div class="add-model-section">
      <h4>➕ 添加新模型</h4>
      <div class="add-model-form">
        <el-input
          v-model="newModelConfig.name"
          placeholder="给这个配置起个名字（如：我的 DeepSeek）"
        />
        <el-select
          v-model="newModelConfig.provider"
          @change="handleModelProviderChange(newModelConfig)"
        >
          <el-option label="DeepSeek" value="deepseek" />
          <el-option label="小米大模型" value="xiaomi" />
        </el-select>
        <el-input
          v-model="newModelConfig.api_base"
          placeholder="服务地址"
        />
        <el-input
          v-model="newModelConfig.model_name"
          placeholder="模型名称"
        />
        <el-button type="primary" @click="addModelConfig">
          添加模型
        </el-button>
      </div>
    </div>
  </div>

  <!-- 功能说明 -->
  <div class="feature-tip">
    <p><strong>🎯 模型用途：</strong></p>
    <ul>
      <li>📝 <strong>智能标题生成</strong> - 根据产品信息自动生成抖音商品标题</li>
      <li>🏷️ <strong>智能分类</strong> - 自动识别商品类目</li>
      <li>💬 <strong>卖点提取</strong> - 提取产品卖点和关键词</li>
    </ul>
  </div>
</template>

<style lang="scss" scoped>
@use "./section";

// 模型配置列表
.model-configs-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-bottom: 20px;
}

.model-config-item {
  padding: 16px;
  background: rgba(92, 124, 250, 0.03);
  border: 1px solid rgba(92, 124, 250, 0.1);
  border-radius: 8px;
}

.model-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.model-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-name {
  font-weight: 600;
  font-size: 14px;
}

.model-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.model-details {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.detail-row {
  display: flex;
  flex-direction: column;
  gap: 4px;

  label {
    font-size: 12px;
    color: var(--text-secondary);
  }
}

// 添加模型
.add-model-section {
  padding: 16px;
  background: rgba(105, 219, 124, 0.05);
  border: 1px dashed rgba(105, 219, 124, 0.4);
  border-radius: 8px;

  h4 {
    margin: 0 0 12px;
    font-size: 14px;
    color: var(--success-color);
  }
}

.add-model-form {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;

  .el-button {
    grid-column: span 2;
    justify-self: start;
  }
}

// 功能说明
.feature-tip {
  padding: 12px 16px;
  background: rgba(92, 124, 250, 0.05);
  border-radius: 8px;
  font-size: 13px;

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
</style>
