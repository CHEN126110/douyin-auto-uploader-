<script setup lang="ts">
import { ref } from "vue";
import type { SKU } from "@/types";

const props = defineProps<{
  skus: SKU[];
  selectedPaths: Set<string>;
  duplicatePaths?: Set<string>;
}>();

const emit = defineEmits<{
  (e: "select", sku: SKU): void;
  (e: "delete", sku: SKU): void;
  (e: "update:sku", sku: SKU): void;
}>();

// 预览大图
const previewVisible = ref(false);
const previewUrl = ref("");
const previewPosition = ref({ x: 0, y: 0 });

// 是否选中
function isSelected(sku: SKU): boolean {
  return props.selectedPaths.has(sku.path);
}

function isDuplicate(sku: SKU): boolean {
  return props.duplicatePaths?.has(sku.path) ?? false;
}

// 显示预览
function showPreview(sku: SKU, event: MouseEvent) {
  if (!sku.url) return;
  previewUrl.value = sku.url;
  previewPosition.value = {
    x: Math.min(event.clientX + 20, window.innerWidth - 240),
    y: Math.min(event.clientY - 110, window.innerHeight - 240),
  };
  previewVisible.value = true;
}

// 隐藏预览
function hidePreview() {
  previewVisible.value = false;
}

// 更新SKU数据
function updateSkuName(sku: SKU, value: string) {
  sku.name = value;
}

function updateSkuPrice(sku: SKU, value: number) {
  sku.price = value;
}
</script>

<template>
  <div class="sku-list-container">
    <!-- 标题行 -->
    <div class="sku-header">
      <div class="sku-header-item thumbnail-col"></div>
      <div class="sku-header-item name-col">SKU名称</div>
      <div class="sku-header-item price-col">价格</div>
      <div class="sku-header-item action-col"></div>
    </div>

    <!-- SKU列表 -->
    <el-scrollbar class="sku-scroll">
      <div
        v-for="sku in skus"
        :key="sku.path"
        class="sku-item"
        :class="{ selected: isSelected(sku), 'has-duplicate': isDuplicate(sku) }"
      >
        <!-- 缩略图 -->
        <div class="sku-thumbnail-wrapper">
          <img
            class="sku-thumbnail"
            :class="{ 'sku-selected': isSelected(sku) }"
            :src="sku.url || 'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNTAiIGhlaWdodD0iNTAiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHJlY3Qgd2lkdGg9IjUwIiBoZWlnaHQ9IjUwIiBmaWxsPSIjZjVmNWY1Ii8+PHRleHQgeD0iMjUiIHk9IjI1IiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTAiIGZpbGw9IiM5OTkiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5ObyBJbWFnZTwvdGV4dD48L3N2Zz4='"
            :alt="sku.name"
            :draggable="false"
            loading="lazy"
            decoding="async"
            @click="emit('select', sku)"
            @mouseenter="showPreview(sku, $event)"
            @mouseleave="hidePreview"
            @dragstart.prevent
          />
        </div>

        <!-- SKU名称 -->
        <el-input
          :model-value="sku.name"
          placeholder="SKU名称"
          :class="['sku-name-input', { 'is-duplicate': isDuplicate(sku) }]"
          @update:model-value="updateSkuName(sku, $event)"
        />

        <!-- 价格 -->
        <el-input
          :model-value="sku.price"
          placeholder="价格"
          type="number"
          class="sku-price-input"
          @update:model-value="updateSkuPrice(sku, Number($event) || 0)"
        />

        <!-- 删除按钮 -->
        <el-button
          type="danger"
          class="sku-delete-btn"
          @click="emit('delete', sku)"
        >
          删除
        </el-button>
      </div>

      <!-- 空状态 -->
      <div v-if="skus.length === 0" class="empty-sku">
        暂无SKU数据
      </div>
    </el-scrollbar>

    <!-- 预览大图 -->
    <Teleport to="body">
      <div
        v-show="previewVisible"
        class="sku-preview-panel"
        :style="{
          left: previewPosition.x + 'px',
          top: previewPosition.y + 'px',
        }"
      >
        <img :src="previewUrl" alt="预览" :draggable="false" @dragstart.prevent />
      </div>
    </Teleport>
  </div>
</template>

<style lang="scss" scoped>
.sku-list-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--card-background);
  border: 1px solid var(--border-color-white);
  border-radius: var(--radius-md);
}

// 标题行
.sku-header {
  display: flex;
  align-items: center;
  padding: 18px 16px;
  background: rgba(255, 255, 255, 0.98);
  border-bottom: 1px solid rgba(92, 124, 250, 0.1);
  position: sticky;
  top: 0;
  z-index: 10;
}

.sku-header-item {
  color: var(--text-primary);
  font-weight: 600;
  font-size: var(--font-size-base);

  &.thumbnail-col {
    width: 66px;
  }

  &.name-col {
    flex: 1;
  }

  &.price-col {
    width: 120px;
    text-align: center;
  }

  &.action-col {
    width: 70px;
  }
}

// 滚动区域
.sku-scroll {
  flex: 1;
  padding: 0 8px;
}

// SKU项
.sku-item {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 4px 12px;
  padding: 8px 12px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid var(--border-color-white);
  border-radius: var(--radius-sm);
  transition: all var(--transition-base) ease;

  &:first-child {
    margin-top: 8px;
  }

  &:last-child {
    margin-bottom: 8px;
  }

  &:hover {
    background: rgba(255, 255, 255, 0.85);
  }

  &.selected {
    background: rgba(92, 124, 250, 0.08);
    border-color: var(--primary-color);
  }

  &.has-duplicate {
    position: relative;
    align-items: flex-start;
    padding-bottom: 24px;
    border-color: rgba(245, 108, 108, 0.55);
    background: rgba(254, 240, 240, 0.72);

    &::after {
      content: "SKU 名称重复，请修改";
      position: absolute;
      left: 84px;
      bottom: 6px;
      font-size: 12px;
      line-height: 1;
      color: #f56c6c;
    }
  }
}

// 缩略图
.sku-thumbnail-wrapper {
  flex-shrink: 0;
}

.sku-thumbnail {
  width: 50px;
  height: 50px;
  object-fit: cover;
  border: 2px solid var(--border-color);
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: all var(--transition-base) ease;

  &:hover {
    border-color: var(--border-color-primary);
  }

  &.sku-selected {
    border-color: var(--primary-color);
    transform: scale(1.05);
    box-shadow: 0 0 20px var(--primary-shadow);
  }
}

// 输入框
.sku-name-input {
  flex: 0.95;  // 缩小5%，留出右侧空间
  min-width: 100px;
}

.sku-name-input.is-duplicate {
  :deep(.el-input__wrapper) {
    box-shadow: 0 0 0 1px #f56c6c inset !important;
  }

  :deep(.el-input__wrapper:hover) {
    box-shadow: 0 0 0 1px #f56c6c inset !important;
  }

  :deep(.el-input__wrapper.is-focus) {
    box-shadow: 0 0 0 1px #f56c6c inset !important;
  }
}

.sku-price-input {
  width: 100px;
  flex-shrink: 0;
}

// 删除按钮 - 与输入框同高
.sku-delete-btn {
  height: 38px !important;
  min-width: 75px !important;
  padding: 0 20px !important;
  flex-shrink: 0;
}

// 空状态
.empty-sku {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 20px;
  font-size: var(--font-size-sm);
}

// 预览面板
.sku-preview-panel {
  position: fixed;
  width: 220px;
  height: 220px;
  z-index: var(--z-tooltip);
  border: 2px solid var(--primary-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xl);
  background: var(--card-background-solid);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  pointer-events: none;

  img {
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
  }
}
</style>
