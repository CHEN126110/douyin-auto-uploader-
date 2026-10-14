<template>
  <el-card class="xhs-panel" shadow="never">
    <template #header>
      <div class="xhs-header">
        <span>小红书千帆（fill_only：只填满，不提交）</span>
        <el-button size="small" :loading="checking" @click="checkStatus">体检</el-button>
      </div>
    </template>

    <el-alert v-if="statusError" type="warning" :closable="false" :title="statusError" show-icon />

    <el-descriptions v-if="status" :column="2" size="small" border class="xhs-desc">
      <el-descriptions-item label="调试端口">{{ status.port }}</el-descriptions-item>
      <el-descriptions-item label="标签页可见性">{{ status.visibility }}</el-descriptions-item>
      <el-descriptions-item label="当前页" :span="2">{{ status.url || '(未知)' }}</el-descriptions-item>
      <el-descriptions-item label="标题计数器">{{ status.title_counter || '(空)' }}</el-descriptions-item>
      <el-descriptions-item label="素材空间抽屉">
        {{ status.drawer && status.drawer.drawers ? '开着（会挡住点击）' : '已关' }}
      </el-descriptions-item>
    </el-descriptions>

    <ul v-if="status && status.category_lines && status.category_lines.length" class="xhs-lines">
      <li v-for="(line, index) in status.category_lines" :key="index">{{ line }}</li>
    </ul>

    <el-descriptions v-if="status && status.gaps" :column="1" size="small" border class="xhs-desc">
      <el-descriptions-item label="必填缺口">
        <span v-if="status.gaps.error">判据读取失败：{{ status.gaps.error }}</span>
        <template v-else-if="status.gaps.unfilled && status.gaps.unfilled.length">
          <el-tag v-for="item in status.gaps.unfilled" :key="item" type="warning" size="small"
                  class="xhs-tag">{{ item }}</el-tag>
        </template>
        <span v-else-if="status.gaps.required_count">
          无缺口（{{ status.gaps.required_count }} 项必填均已填）
        </span>
        <span v-else>（当前页没有必填标记，可能不在创建页）</span>
      </el-descriptions-item>
      <el-descriptions-item label="完成度判据">
        {{ judgeSummary }}
      </el-descriptions-item>
    </el-descriptions>

    <el-divider />

    <p class="xhs-hint">
      本卡片只做**只读体检**（计划 3.1）。填表入口统一在「商品管理」页的「小红书填表」，
      这里不再放第二个填表按钮 —— 两套入口会各传一份参数，参数一旦不一致就难查 ✗。
    </p>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { api } from '../services/api'

type XhsStatus = Awaited<ReturnType<typeof api.getXhsStatus>>['data']

const status = ref<XhsStatus | null>(null)
const statusError = ref('')
const checking = ref(false)

/** 把三套完成度判据拼成一行（各取第一条，缺失则跳过）。 */
const judgeSummary = computed(() => {
  const judges = status.value?.gaps?.judges
  const parts = [judges?.key_attrs?.[0], judges?.other_attrs?.[0], judges?.required?.[0]]
  return parts.filter(Boolean).join(' ｜ ') || '（无）'
})

async function checkStatus() {
  checking.value = true
  statusError.value = ''
  try {
    const response = await api.getXhsStatus()
    status.value = (response?.data ?? null) as XhsStatus | null
  } catch (error) {
    status.value = null
    // 端口不写死 ✗：来源是接口返回的 status.port（唯一来源，见计划 3.2）。
    // 接口不可达时拿不到端口，就如实说"不可达"，不编一个数字。
    statusError.value = `小红书调试浏览器不可达：${String(error)}`
  } finally {
    checking.value = false
  }
}
</script>

<style scoped>
.xhs-panel { max-width: 900px; }
.xhs-header { display: flex; align-items: center; justify-content: space-between; }
.xhs-desc { margin-bottom: 8px; }
.xhs-lines { margin: 6px 0 0; padding-left: 18px; font-size: 13px; color: #606266; }
.xhs-blocked { color: #b88230; }
.xhs-hint { margin-left: 10px; font-size: 12px; color: #909399; }
</style>
