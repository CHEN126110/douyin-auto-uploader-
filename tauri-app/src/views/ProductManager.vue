<script setup lang="ts">
import { useRouter } from "vue-router";
import { useProductStore } from "@/stores/productStore";
import { CATEGORY_OPTIONS } from "@/types";
import { useShopAccount } from "@/composables/useShopAccount";
import { useExternalUploadDiscovery, useUploadTaskMonitor } from "@/composables/useUploadTaskMonitor";
import { useSkuList } from "@/composables/useSkuList";
import { useProductForm } from "@/composables/useProductForm";
import { useSmartPricing } from "@/composables/useSmartPricing";
import { usePublishFlow } from "@/composables/usePublishFlow";
import { useProductList } from "@/composables/useProductList";
import SkuList from "@/components/SkuList.vue";
import CaptureSection from "@/components/CaptureSection.vue";
import ContextMenu from "@/components/ContextMenu.vue";
import ShopStatusBar from "@/components/ShopStatusBar.vue";
import ProductMediaManager from "@/components/ProductMediaManager.vue";
import UploadProgressPanel from "@/components/UploadProgressPanel.vue";
import PricingResultsDialog from "@/components/PricingResultsDialog.vue";

/**
 * 主页（商品管理）：把左侧商品目录、右侧商品表单、发布流程装配到一起。
 * 具体逻辑按职责放在 composables/ 里，这里只负责按依赖顺序创建它们、把需要的东西接到模板上：
 *
 * - useShopAccount        当前账户（账户栏 → store）
 * - useUploadTaskMonitor  上传 / 发布任务的监控与忙碌状态 uploadBusy（其它操作都要看它让路）
 * - useSkuList            SKU 勾选、重复名检查
 * - useProductForm        商品表单、保存、简单填充价格
 * - useSmartPricing       智能填充价格与成本分析弹窗
 * - usePublishFlow        发起发布（抖音 / 淘宝 / 小红书 / 批量）
 * - useProductList        商品目录点选、右键菜单、清空全部
 * - useExternalUploadDiscovery  接上别处已在进行的任务
 */
const productStore = useProductStore();
const router = useRouter();

const shop = useShopAccount();
const { shopStatusBarRef, shopAccountBusy, handleShopSessionChanged } = shop;

const monitor = useUploadTaskMonitor();
const {
  uploadBusy,
  isUploadMonitoring,
  uploadStatusText,
  uploadProgress,
  uploadSteps,
  taobaoUnknownStart,
  uploadMonitoringPaused,
  activeUploadTaskId,
  uploadTaskCancelling,
  retryUploadProgress,
  cancelUploadTask,
} = monitor;

const skuList = useSkuList({ uploadBusy });
const { selectedSkuPaths, duplicateSkuPaths, handleCancelSelect, handleSkuSelect, handleSkuDelete } = skuList;

const productForm = useProductForm({
  uploadBusy,
  selectedSkuPaths: skuList.selectedSkuPaths,
  duplicateSkuGroups: skuList.duplicateSkuGroups,
  showDuplicateSkuAlert: skuList.showDuplicateSkuAlert,
});
const { formData, titleLength, handleSave, handleSimpleFill } = productForm;

const { smartFillLoading, pricingResultsVisible, pricingResultsData, handleSmartFill } = useSmartPricing({
  uploadBusy,
  formData,
});

const { publishPlatformLabel, publishActionText, publishButtonDisabled, handlePublishByAccount, handleBatchUploadAll } =
  usePublishFlow({
    monitor,
    shop,
    formData,
    productSaveData: productForm.productSaveData,
    collectDuplicateSkuGroups: skuList.collectDuplicateSkuGroups,
    showDuplicateSkuAlert: skuList.showDuplicateSkuAlert,
  });

const {
  contextMenuVisible,
  contextMenuPosition,
  mediaManagerVisible,
  mediaManagerProductId,
  handleProductClick,
  handleProductMenuKey,
  handleContextMenu,
  handleContextMenuAction,
  handleDeleteAll,
} = useProductList({ uploadBusy });

useExternalUploadDiscovery(monitor);

function openSettingsPage() {
  if (uploadBusy.value) return;
  router.push("/settings");
}
</script>

<template>
  <div class="product-manager fade-in">
    <!-- 左侧面板 -->
    <div class="left-panel">
      <!-- 当前账户决定发布平台，平台仅在添加账户时选择。 -->
      <ShopStatusBar
        ref="shopStatusBarRef"
        :paused="uploadBusy"
        @changed="handleShopSessionChanged"
        @busy-change="shopAccountBusy = $event"
      />

      <!-- 链接采集区域 -->
      <CaptureSection @imported="productStore.fetchProducts()" />

      <!-- 产品列表 -->
      <div class="product-list">
        <h2 class="panel-title">本地商品目录</h2>

        <el-scrollbar class="product-scroll">
          <div
            v-for="product in productStore.products"
            :key="product.id"
            class="product-item"
            :class="{ active: product.id === productStore.currentProductId, 'selection-disabled': uploadBusy || productStore.detailLoading }"
            :aria-disabled="uploadBusy || productStore.detailLoading"
            :tabindex="uploadBusy || productStore.detailLoading ? -1 : 0"
            role="button"
            @click="handleProductClick(product.id)"
            @keydown.enter="handleProductClick(product.id)"
            @keydown.space.prevent="handleProductClick(product.id)"
            @keydown.shift.f10.prevent="handleProductMenuKey($event, product.id)"
            @keydown.context-menu.prevent="handleProductMenuKey($event, product.id)"
            @contextmenu="handleContextMenu($event, product.id)"
          >
            <div class="product-icon">📁</div>
            <div class="product-info">
              <span class="product-name">{{ product.name }}</span>
              <span class="product-time">{{ product.update_time }}</span>
            </div>
          </div>

          <div v-if="productStore.products.length === 0" class="empty-tip">
            暂无产品，请拖入文件夹或采集链接
          </div>
        </el-scrollbar>
      </div>
    </div>

    <!-- 右侧表单 -->
    <div class="right-panel" v-loading="productStore.detailLoading">
      <h1 class="form-title">
        {{ publishPlatformLabel ? `${publishPlatformLabel}发布 · ` : "商品配置 · " }}{{ productStore.currentProduct?.name || "请选择商品" }}
      </h1>

      <el-form label-position="top" class="product-form" :disabled="uploadBusy">
        <!-- 类目选择 -->
        <el-form-item>
          <el-select
            v-model="formData.clazz"
            placeholder="请选择类目"
            class="full-width"
          >
            <el-option
              v-for="option in CATEGORY_OPTIONS"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>

        <!-- 商品标题 -->
        <el-form-item>
            <div class="title-input-wrapper">
              <el-input
                v-model="formData.title"
              placeholder="标题"
              class="title-input"
              />
            <span class="word-count" :class="{ 'over-limit': titleLength > 60 }">
              {{ titleLength }}/60
            </span>
          </div>
        </el-form-item>

        <!-- 备注只在下方每个 SKU 行内编辑；商品级 remark 仍随资料保留，不重复展示。 -->

        <!-- 库存和价格 -->
        <el-form-item>
          <div class="price-row">
            <el-input
              v-model.number="formData.repo"
              type="number"
              placeholder="设置库存"
              class="repo-input"
            />
            <el-input
              v-model.number="formData.price"
              type="number"
              placeholder="单价"
              class="price-input"
            />
            <el-button type="warning" @click="handleSimpleFill">
              填充
            </el-button>
            <el-button type="success" @click="handleSmartFill" :loading="smartFillLoading">
              智能填充
            </el-button>
            <el-button type="primary" @click="handleSave">保存</el-button>
          </div>
        </el-form-item>

        <!-- SKU列表 -->
        <SkuList
          :skus="productStore.currentSkus"
          :selected-paths="selectedSkuPaths"
          :duplicate-paths="duplicateSkuPaths"
          @select="handleSkuSelect"
          @delete="handleSkuDelete"
        />

        <!-- 上传进度 -->
        <UploadProgressPanel
          v-if="isUploadMonitoring"
          :status-text="uploadStatusText"
          :progress="uploadProgress"
          :steps="uploadSteps"
        />

        <!-- 底部按钮 -->
        <div class="action-buttons">
          <el-button type="primary" :loading="uploadBusy" :disabled="publishButtonDisabled" @click="handlePublishByAccount">
            {{ publishActionText }}
          </el-button>
          <el-button
            type="success"
            :loading="uploadBusy"
            :disabled="publishButtonDisabled"
            @click="handleBatchUploadAll"
          >
            批量发布全部
          </el-button>
          <el-button type="warning" @click="handleCancelSelect">
            取消勾选
          </el-button>
          <el-button type="danger" @click="handleDeleteAll">
            清空全部
          </el-button>
          <el-button type="info" @click="openSettingsPage">
            ⚙️ 设置
          </el-button>
        </div>
      </el-form>
      <div v-if="taobaoUnknownStart || uploadMonitoringPaused" class="upload-task-actions">
        <span v-if="taobaoUnknownStart">淘宝填写启动结果待确认</span>
        <el-button @click="retryUploadProgress">重新读取进度</el-button>
        <el-button v-if="activeUploadTaskId" type="warning" :loading="uploadTaskCancelling" @click="cancelUploadTask">取消上传</el-button>
      </div>
    </div>

    <!-- 右键菜单 -->
    <ContextMenu
      v-model:visible="contextMenuVisible"
      :position="contextMenuPosition"
      @action="handleContextMenuAction"
    />
    <ProductMediaManager v-model="mediaManagerVisible" :record-id="mediaManagerProductId" :processing-disabled="uploadBusy" />

    <!-- 智能填充结果弹窗 -->
    <PricingResultsDialog v-model="pricingResultsVisible" :result="pricingResultsData" />

  </div>
</template>

<style lang="scss" scoped>
// 上传进度遮罩由 useUploadTaskMonitor 创建（customClass: product-upload-loading），挂在 body 下，必须用全局选择器
:global(.product-upload-loading .upload-loading-content .el-button) {
  margin-top: 16px;
}

.upload-task-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}

.product-manager {
  display: flex;
  height: 100vh;
  padding: var(--container-padding);
  gap: var(--container-padding);
}

// 左侧面板
.left-panel {
  width: var(--left-panel-width);
  background: var(--card-background);
  border: 1px solid var(--border-color-white);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: all var(--transition-base) ease;

  &:hover {
    background: var(--card-background-hover);
    box-shadow: var(--shadow-xl);
  }
}

.product-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 10px 20px;
}

.panel-title {
  text-align: center;
  font-weight: 700;
  padding: 15px 0;
  color: var(--text-primary);
  font-size: var(--font-size-xl);
  position: relative;

  &::after {
    content: "";
    position: absolute;
    bottom: 8px;
    left: 50%;
    transform: translateX(-50%);
    width: 40px;
    height: 2px;
    background: var(--primary-gradient);
    border-radius: 1px;
  }
}

.product-scroll {
  flex: 1;
}

.product-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 12px;
  margin: 2px 0;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-base) ease;

  &:hover {
    background: rgba(92, 124, 250, 0.08);

    .product-name {
      color: var(--primary-color);
    }
  }

  &:active {
    transform: scale(0.99);
    background: rgba(92, 124, 250, 0.12);
  }

  &.active {
    background: linear-gradient(
      90deg,
      rgba(92, 124, 250, 0.15) 0%,
      rgba(92, 124, 250, 0.06) 100%
    );
    border-radius: var(--radius-sm);

    .product-name {
      color: var(--primary-color);
      font-weight: 600;
    }
  }

  &.selection-disabled {
    cursor: wait;
  }

  &:focus-visible {
    outline: 2px solid var(--primary-color);
    outline-offset: -2px;
  }
}

.product-icon {
  font-size: 16px;
}

.product-info {
  flex: 1;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.product-name {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  font-weight: 500;
}

.product-time {
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.empty-tip {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 20px;
  font-size: var(--font-size-sm);
}

// 右侧面板
.right-panel {
  flex: 1;
  min-width: 0;
  background: var(--card-background);
  border: 1px solid var(--border-color-white);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--container-padding);
  display: flex;
  flex-direction: column;
  overflow: hidden;  // 保持内容不溢出
}

.form-title {
  text-align: center;
  margin-bottom: 24px;
  color: var(--text-primary);
  font-weight: 700;
  font-size: var(--font-size-title);
  position: relative;
  padding-bottom: 15px;

  &::after {
    content: "";
    position: absolute;
    bottom: 0;
    left: 50%;
    transform: translateX(-50%);
    width: 60px;
    height: 2px;
    background: var(--primary-gradient);
    border-radius: 1px;
  }
}

.product-form {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;  // 保持内容不溢出
  min-height: 0;  // 重要：允许flex容器收缩
  
  // 让表单项不要收缩
  :deep(.el-form-item) {
    flex-shrink: 0;
  }
  
  // 让SKU列表区域可滚动并填充剩余空间
  :deep(.sku-list-container) {
    flex: 1;
    min-height: 0;  // 重要：允许flex子项收缩
    overflow: hidden;
  }
}

.full-width {
  width: 100%;
}

.title-input-wrapper {
  position: relative;
  width: 100%;

  .title-input {
    :deep(.el-input__inner) {
      padding-right: 60px;
    }
  }

  .word-count {
    position: absolute;
    right: 12px;
    top: 50%;
    transform: translateY(-50%);
    color: #999;
    font-size: 12px;
    pointer-events: none;

    &.over-limit {
      color: red;
    }
  }
}

.price-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;

  .repo-input {
    width: 103px;
  }

  .price-input {
    width: 100px;
  }
}

.action-buttons {
  display: flex;
  gap: var(--button-gap);
  padding-top: var(--container-padding);
  margin-top: auto;
  flex-shrink: 0;  // 不允许收缩，始终显示
}
</style>
