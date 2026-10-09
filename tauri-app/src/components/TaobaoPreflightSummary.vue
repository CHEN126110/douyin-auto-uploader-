<script setup lang="ts">
import { computed } from "vue";
import type { TaobaoPreparation, TaobaoPreparationCheck, TaobaoReadiness } from "@/types";

const props = defineProps<{
  checking: boolean;
  readiness: TaobaoReadiness | null;
  report: TaobaoPreparation | null;
  error: string;
}>();

const missing = computed(() => props.report?.checks.filter((check) => check.status === "missing") || []);
const warnings = computed(() => props.report?.checks.filter((check) => check.status === "warning") || []);

function statusLabel(check: TaobaoPreparationCheck) {
  return { ok: "已具备", warning: "待核对", missing: "缺少资料" }[check.status];
}

function statusType(check: TaobaoPreparationCheck): "success" | "warning" | "danger" {
  return check.status === "ok" ? "success" : check.status === "warning" ? "warning" : "danger";
}
</script>

<template>
  <section class="taobao-preflight-summary" aria-label="淘宝资料检查" aria-live="polite">
    <p class="capability-note">淘宝平台上传、自动填写与回读尚未接入；当前仅检查本地资料，尚未完成平台必填项验证。</p>
    <p v-if="checking" class="check-progress" role="status">正在检查当前商品的淘宝资料，请稍候…</p>
    <el-alert v-else-if="error" :title="error" type="error" :closable="false" show-icon />
    <template v-else-if="report">
      <div class="report-heading">
        <strong>本地资料检查完成，尚未发布</strong>
        <span>缺少 {{ missing.length }} 项 · 待核对 {{ warnings.length }} 项</span>
      </div>
      <div class="asset-counts">
        <span>主图 {{ report.assets.main.length }} 张</span>
        <span>详情图 {{ report.assets.detail.length }} 张</span>
        <span>规格图 {{ report.assets.sku.length }} 张</span>
        <span>白底图 {{ report.assets.white_bg ? 1 : 0 }} 张</span>
      </div>
      <ul v-if="missing.length" class="missing-preview">
        <li v-for="check in missing.slice(0, 3)" :key="check.field">{{ check.label }}：{{ check.message }}</li>
        <li v-if="missing.length > 3">另外 {{ missing.length - 3 }} 项缺失，请展开完整检查结果查看。</li>
      </ul>
      <details class="report-details">
        <summary>查看完整检查结果（{{ report.checks.length }} 项）</summary>
        <div class="details-table">
          <el-table :data="report.checks" size="small" border max-height="190">
            <el-table-column prop="label" label="检查项" min-width="100" />
            <el-table-column label="状态" width="98">
              <template #default="{ row }">
                <el-tag :type="statusType(row)" size="small">{{ statusLabel(row) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="message" label="实际情况与缺项" min-width="220" />
          </el-table>
          <p v-if="readiness" class="readiness-message">{{ readiness.message }}</p>
        </div>
      </details>
    </template>
  </section>
</template>

<style scoped>
.taobao-preflight-summary {
  flex: none;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--radius-md);
  background: var(--el-fill-color-light);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
}

.capability-note,
.check-progress,
.readiness-message {
  margin: 0;
  overflow-wrap: anywhere;
}

.check-progress,
.report-heading,
.asset-counts,
.report-details,
.readiness-message {
  margin-top: 6px;
}

.report-heading,
.asset-counts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.asset-counts,
.report-heading span {
  color: var(--text-secondary);
}

.missing-preview {
  margin: 6px 0;
  padding-left: 18px;
  overflow-wrap: anywhere;
}

.report-details summary {
  cursor: pointer;
  color: var(--primary-color);
}

.details-table {
  margin-top: 8px;
}
</style>
