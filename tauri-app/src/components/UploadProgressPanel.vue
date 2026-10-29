<script setup lang="ts">
import type { UploadProgressStep } from "@/types";

// 上传 / 发布进行中的进度条与步骤列表；数据由 useUploadTaskMonitor 提供，这里只负责展示。
defineProps<{
  statusText: string;
  progress: number;
  steps: UploadProgressStep[];
}>();
</script>

<template>
  <!-- 上传进度 -->
    <div class="upload-status">
      <div class="status-header">
        <div class="status-spinner"></div>
        <span class="status-text">{{ statusText }}</span>
        <span class="status-pct">{{ progress }}%</span>
      </div>
      <div class="status-progress-bar">
        <div class="progress-fill" :style="{ width: progress + '%' }"></div>
      </div>
      <div v-if="steps.length > 0" class="status-steps">
        <div
          v-for="(step, i) in steps"
          :key="i"
          class="step-item"
          :class="'step-' + step.status"
        >
          <span class="step-icon">{{ step.status === 'ok' ? '✓' : step.status === 'failed' ? '✗' : '○' }}</span>
          <span class="step-name">{{ step.label || step.name }}</span>
          <span v-if="step.elapsed_ms != null" class="step-time">{{ step.elapsed_ms }}ms</span>
          <span v-if="step.summary" class="step-summary">{{ step.summary }}</span>
        </div>
      </div>
    </div>
</template>

<style lang="scss" scoped>
// 上传步骤进度
.upload-status {
  background: #f8f9fc;
  border: 1px solid #e4e7ed;
  border-radius: var(--radius-sm, 8px);
  padding: 12px 16px;
  margin-top: 12px;

  .status-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
  }

  .status-spinner {
    width: 16px;
    height: 16px;
    border: 2px solid #e4e7ed;
    border-top-color: #5c7cfa;
    border-radius: 50%;
    animation: upload-spin 0.8s linear infinite;
  }

  @keyframes upload-spin {
    to { transform: rotate(360deg); }
  }

  .status-text {
    flex: 1;
    font-size: 13px;
    color: #303133;
  }

  .status-pct {
    font-size: 12px;
    color: #909399;
  }

  .status-progress-bar {
    height: 4px;
    background: #e4e7ed;
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 8px;

    .progress-fill {
      height: 100%;
      background: #5c7cfa;
      border-radius: 2px;
      transition: width 0.3s ease;
    }
  }

  .status-steps {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }

  .step-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    padding: 3px 6px;
    border-radius: 4px;

    &.step-ok {
      color: #67c23a;
      background: rgba(103, 194, 58, 0.06);
    }

    &.step-failed {
      color: #f56c6c;
      background: rgba(245, 108, 108, 0.06);
    }

    &.step-running {
      color: #5c7cfa;
      background: rgba(92, 124, 250, 0.06);
    }
  }

  .step-icon {
    width: 16px;
    text-align: center;
    font-weight: bold;
  }

  .step-name {
    min-width: 100px;
    font-weight: 500;
  }

  .step-time {
    color: #909399;
    font-size: 11px;
  }

  .step-summary {
    color: #606266;
    font-size: 11px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    max-width: 200px;
  }
}
</style>
