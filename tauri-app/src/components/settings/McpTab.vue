<script setup lang="ts">
import { computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import {
  CircleCheck,
  Connection,
  CopyDocument,
  Document,
  InfoFilled,
  Refresh,
  Warning,
} from "@element-plus/icons-vue";
import { tauriCommands } from "@/services/api";
import { useMcpGuide } from "@/composables/settings/useMcpGuide";

// 只读页：展示本机真实检测结果，不参与设置保存。
const {
  appInfo,
  loading,
  loadError,
  loadAppInfo,
} = useMcpGuide();

const mcpReady = computed(() =>
  appInfo.value.mcp_executable_exists || appInfo.value.mcp_server_entry_exists
);
const skillReady = computed(() => appInfo.value.skill_dir_exists);
const runtimeReady = computed(() =>
  appInfo.value.mcp_executable_exists || appInfo.value.bundled_node_exists
);
const availableMethods = computed(() => {
  const methods = [];
  if (skillReady.value) methods.push("Skill");
  if (mcpReady.value) methods.push("MCP");
  return methods;
});
const summaryText = computed(() => {
  if (availableMethods.value.length === 2) {
    return "当前两种方式都可以使用。复制同一段提示词即可，Agent 会自行选择，不需要你判断。";
  }
  if (availableMethods.value.length === 1) {
    return `当前可以使用 ${availableMethods.value[0]}。复制同一段提示词即可，不需要额外配置。`;
  }
  return "当前没有检测到可用的连接内容。提示词仍可复制，但 Agent 会如实提示尚未连接，不会假装调用成功。";
});

const agentPrompt = `请使用“电商产品发布工具”协助我处理商品。

请先自动检查当前环境是否提供以下任意一种能力：
1. 名为 douyin-publisher-mcp 的 Skill；
2. 名为 douyin-publisher 的 MCP 服务或相关工具。

只找到其中一种也可以直接使用，不要求两者同时存在，也不要让我提供文件路径或重复安装。
如果找到 Skill，请先阅读并遵循其中的操作指导；如果找到 MCP，请先查看可用工具并执行健康检查。
如果两种方式都找到，按 Skill 的安全顺序组织流程，通过可用的 MCP 工具执行。
如果都没有找到，请明确告诉我“尚未连接到电商产品发布工具”，不要假装已经连接或调用成功。

连接后请遵守：
1. 先检查服务状态和当前店铺账户，告诉我实际支持哪些平台和操作。
2. 按工具指导完成商品采集、资料整理、标题、定价和发布前检查，不要跳过必要校验。
3. 主图、详情图和 SKU 图片必须按各自用途使用，不要混用。
4. 任何真实发布、保存草稿或提交操作，都必须先向我说明目标店铺和将执行的动作，并得到我的明确确认。
5. 只填表不等于已发布；任务结束不等于上架成功。请如实报告完成、失败或仍需人工处理的部分。

现在请先完成连接检查，简短告诉我可以使用 Skill、MCP，还是尚未连接，然后等待我提供商品链接或商品目录。`;

async function copyGuideText(text: string, label: string) {
  try {
    await tauriCommands.writeClipboardText(text);
    ElMessage.success(`${label}已复制`);
  } catch (error) {
    console.error(`复制${label}失败:`, error);
    ElMessage.error(`复制${label}失败，请手动复制`);
  }
}

onMounted(() => {
  void loadAppInfo();
});
</script>

<template>
  <section class="extension-hero">
    <div class="hero-content">
      <div class="hero-eyebrow">可选功能</div>
      <h2>复制一段提示词，让 Agent 帮你处理商品</h2>
      <p>
        不需要理解 Skill、MCP 或文件路径。把下面的提示词粘贴到你的 Agent，
        它会自动检查能使用哪种方式；日常直接使用本工具时，无需配置本页。
      </p>
    </div>
    <el-button type="primary" size="large" :icon="CopyDocument" @click="copyGuideText(agentPrompt, 'Agent 提示词')">
      复制提示词
    </el-button>
  </section>

  <section class="settings-section prompt-section">
    <div class="section-header">
      <div>
        <h3 class="section-title">直接粘贴这段提示词</h3>
        <p class="section-desc">已包含自动识别、健康检查、图片用途和发布确认要求。</p>
      </div>
      <el-button size="small" :icon="CopyDocument" @click="copyGuideText(agentPrompt, 'Agent 提示词')">
        复制
      </el-button>
    </div>
    <pre class="agent-prompt">{{ agentPrompt }}</pre>
  </section>

  <section class="settings-section">
    <h3 class="section-title">粘贴后，Agent 会这样处理</h3>
    <div class="usage-steps">
      <div><span>1</span><p><strong>自动识别</strong>检查 Skill 或 MCP，找到任意一种即可。</p></div>
      <div><span>2</span><p><strong>先检查再操作</strong>确认服务和店铺状态，按工具指导执行。</p></div>
      <div><span>3</span><p><strong>发布前问你</strong>真实提交前必须获得你的明确确认。</p></div>
    </div>
  </section>

  <section class="settings-section">
    <h3 class="section-title">
      <el-icon class="section-icon"><InfoFilled /></el-icon>
      当前支持情况
    </h3>
    <p class="section-desc">这里只用于让你确认当前环境，不需要打开目录或修改配置。</p>

    <div v-if="loading" class="checking-card">
      <el-icon class="is-loading"><Refresh /></el-icon>
      正在检查支持情况…
    </div>
    <div v-else-if="loadError" class="checking-card warning">
      <el-icon><Warning /></el-icon>
      <span>{{ loadError }}</span>
      <el-button size="small" @click="loadAppInfo">重新检查</el-button>
    </div>

    <template v-else>
      <div class="resource-grid">
        <article class="resource-card" :class="{ ready: skillReady }">
          <div class="resource-heading"><el-icon><Document /></el-icon><h4>Skill 操作指南</h4></div>
          <p>指导 Agent 按正确顺序使用商品功能。</p>
          <div class="resource-state" :class="skillReady ? 'ok' : 'missing'">
            <el-icon><CircleCheck v-if="skillReady" /><Warning v-else /></el-icon>
            {{ skillReady ? "可以使用" : "未检测到" }}
          </div>
        </article>
        <article class="resource-card" :class="{ ready: mcpReady }">
          <div class="resource-heading"><el-icon><Connection /></el-icon><h4>MCP 连接服务</h4></div>
          <p>让 Agent 调用本工具提供的实际商品能力。</p>
          <div class="resource-state" :class="mcpReady ? 'ok' : 'missing'">
            <el-icon><CircleCheck v-if="mcpReady" /><Warning v-else /></el-icon>
            {{ mcpReady ? "可以使用" : "未检测到" }}
          </div>
        </article>
        <article class="resource-card" :class="{ ready: runtimeReady }">
          <div class="resource-heading"><el-icon><InfoFilled /></el-icon><h4>运行组件</h4></div>
          <p>负责运行连接服务，已准备好时无需另外安装。</p>
          <div class="resource-state" :class="runtimeReady ? 'ok' : 'missing'">
            <el-icon><CircleCheck v-if="runtimeReady" /><Warning v-else /></el-icon>
            {{ runtimeReady ? "已随应用提供" : "未检测到内置组件" }}
          </div>
        </article>
      </div>
      <div class="resource-summary">{{ summaryText }}</div>
    </template>
  </section>

</template>

<style lang="scss" scoped>
@use "./section";

.extension-hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 22px;
  padding: 22px 24px;
  margin-bottom: 24px;
  border: 1px solid rgba(92, 124, 250, 0.16);
  border-radius: 14px;
  background: linear-gradient(135deg, rgba(92, 124, 250, 0.10), rgba(92, 124, 250, 0.03));

  .hero-content { min-width: 0; }
  .hero-eyebrow { margin-bottom: 8px; color: var(--primary-color); font-size: 12px; font-weight: 600; }
  h2 { margin: 0 0 10px; color: var(--text-primary); font-size: 21px; line-height: 1.4; }
  p { margin: 0; color: var(--text-secondary); font-size: 14px; line-height: 1.8; }
  > .el-button { flex: none; }
}

.section-desc {
  margin: 5px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}
.section-header { align-items: flex-start; }

.prompt-section { margin-bottom: 22px; }
.agent-prompt {
  max-height: 420px;
  margin: 0;
  padding: 18px;
  overflow: auto;
  border: 1px solid rgba(92, 124, 250, 0.14);
  border-radius: 10px;
  background: rgba(92, 124, 250, 0.045);
  color: var(--text-primary);
  font-family: inherit;
  font-size: 13px;
  line-height: 1.8;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  user-select: text;
}

.usage-steps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;

  > div {
    display: flex;
    gap: 10px;
    padding: 14px;
    border: 1px solid rgba(92, 124, 250, 0.12);
    border-radius: 10px;
  }
  span {
    display: inline-flex;
    flex: 0 0 24px;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: rgba(92, 124, 250, 0.10);
    color: var(--primary-color);
    font-size: 12px;
    font-weight: 600;
  }
  p { margin: 2px 0 0; color: var(--text-secondary); font-size: 13px; line-height: 1.65; }
  strong { display: block; margin-bottom: 3px; color: var(--text-primary); }
}

.checking-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px;
  border: 1px solid rgba(92, 124, 250, 0.12);
  border-radius: 10px;
  color: var(--text-secondary);

  &.warning { color: var(--el-color-warning-dark-2); }
  .el-button { margin-left: auto; }
}

.resource-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}
.resource-card {
  min-width: 0;
  padding: 17px;
  border: 1px solid var(--border-color);
  border-radius: 12px;
  background: #fff;

  &.ready { border-color: rgba(47, 158, 68, 0.22); }
  .resource-heading {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 10px;
    color: var(--primary-color);
    h4 { margin: 0; color: var(--text-primary); font-size: 15px; }
  }
  p { margin: 0 0 12px; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
  .resource-state {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 600;
    &.ok { color: var(--success-color); }
    &.missing { color: var(--el-color-warning-dark-2); }
  }
}
.resource-summary {
  margin-top: 14px;
  padding: 11px 14px;
  border-radius: 8px;
  background: rgba(92, 124, 250, 0.05);
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.advanced-details {
  margin-top: 16px;
  border: 1px solid var(--border-color);
  border-radius: 10px;
  background: rgba(92, 124, 250, 0.025);

  summary { padding: 13px 15px; color: var(--text-secondary); font-size: 13px; cursor: pointer; user-select: none; }
  pre {
    margin: 0;
    padding: 14px;
    overflow: auto;
    border-radius: 8px;
    background: rgba(15, 23, 42, 0.88);
    color: #e2e8f0;
    font-size: 12px;
    line-height: 1.6;
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
}
.advanced-content { padding: 0 14px 14px; }
.advanced-block + .advanced-block { margin-top: 16px; }
.advanced-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  h4 { margin: 0; color: var(--text-primary); font-size: 14px; }
}
.advanced-block p { color: var(--text-secondary); font-size: 12px; overflow-wrap: anywhere; }

@media (max-width: 820px) {
  .extension-hero { align-items: flex-start; flex-direction: column; }
  .usage-steps { grid-template-columns: 1fr; }
}
@media (max-width: 720px) {
  .extension-hero { padding: 18px; }
  .resource-grid { grid-template-columns: 1fr; }
  .advanced-heading { align-items: flex-start; flex-direction: column; }
}
</style>
