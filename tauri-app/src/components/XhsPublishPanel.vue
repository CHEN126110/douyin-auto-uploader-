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

    <el-divider />

    <el-form label-width="96px" size="small" @submit.prevent>
      <el-form-item label="商品标题">
        <el-input v-model="title" maxlength="60" show-word-limit
                  placeholder="16-60 个字符（8-30 个字，汉字按 2 计）" />
      </el-form-item>
      <el-form-item label="图片">
        <el-checkbox v-model="allowUpload">授权上传（写入平台素材空间）</el-checkbox>
        <div class="xhs-hint">未勾选时只会填标题，不会上传任何图片。</div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="running" @click="runFillOnly">填满（不提交）</el-button>
        <span class="xhs-hint">永远不点提交、不点下一步以外的东西</span>
      </el-form-item>
    </el-form>

    <template v-if="report">
      <el-alert :type="report.ok ? 'success' : 'error'" :closable="false" show-icon
                :title="report.ok ? '填写完成（已停在提交前）' : '未能完成'" />
      <ul v-if="report.blocked && report.blocked.length" class="xhs-lines xhs-blocked">
        <li v-for="(item, index) in report.blocked" :key="index">{{ item }}</li>
      </ul>
      <el-descriptions v-if="report.title_check" :column="2" size="small" border>
        <el-descriptions-item label="标题字数">{{ report.title_check.words }} 个字</el-descriptions-item>
        <el-descriptions-item label="平台计数">{{ report.title_check.units }}/60</el-descriptions-item>
      </el-descriptions>
    </template>
  </el-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../services/api'

type XhsStatus = Awaited<ReturnType<typeof api.getXhsStatus>>['data']

type XhsReport = {
  ok: boolean
  blocked?: string[]
  title_check?: { words: number; units: number }
}

const status = ref<XhsStatus | null>(null)
const statusError = ref('')
const checking = ref(false)
const running = ref(false)
const title = ref('')
const allowUpload = ref(false)
const report = ref<XhsReport | null>(null)

async function checkStatus() {
  checking.value = true
  statusError.value = ''
  try {
    const response = await api.getXhsStatus()
    status.value = (response?.data ?? null) as XhsStatus | null
  } catch (error) {
    status.value = null
    statusError.value = `小红书调试浏览器不可达（9336）：${String(error)}`
  } finally {
    checking.value = false
  }
}

async function runFillOnly() {
  if (!title.value.trim()) {
    ElMessage.warning('请先填商品标题')
    return
  }
  running.value = true
  report.value = null
  try {
    // allow_upload 默认 false：不勾选就绝不会触发上传（服务端也会再兜一次默认值）
    const response = await api.xhsFillOnly({
      title: title.value.trim(),
      allow_upload: allowUpload.value,
    })
    report.value = (response?.data ?? null) as XhsReport | null
    if (report.value?.ok === false) ElMessage.warning('未完成，请看下方原因')
  } catch (error) {
    ElMessage.error(`执行失败：${String(error)}`)
  } finally {
    running.value = false
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
