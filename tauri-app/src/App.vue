<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useProductStore } from "@/stores/productStore";
import OnboardingGuide from "@/components/OnboardingGuide.vue";

const productStore = useProductStore();
const isDragging = ref(false);
const onboardingRef = ref<InstanceType<typeof OnboardingGuide> | null>(null);
const unlisteners: Array<() => void> = [];
const PRODUCT_SYNC_INTERVAL_MS = 5000;
let productSyncTimer: number | null = null;

let lastDropSignature = "";
let lastDropTimestamp = 0;
const DROP_DEDUPE_WINDOW_MS = 500;

function showOnboarding() {
  onboardingRef.value?.showOnboarding();
}

function normalizePaths(paths: string[]) {
  return [...new Set(paths.filter((path) => typeof path === "string" && path.trim()))];
}

function shouldSkipDrop(paths: string[]) {
  const signature = [...paths].sort().join("||");
  const now = Date.now();
  const shouldSkip =
    signature === lastDropSignature &&
    now - lastDropTimestamp < DROP_DEDUPE_WINDOW_MS;

  if (!shouldSkip) {
    lastDropSignature = signature;
    lastDropTimestamp = now;
  }

  return shouldSkip;
}

async function handleFilesDropped(paths: string[]) {
  const normalizedPaths = normalizePaths(paths);
  isDragging.value = false;

  if (normalizedPaths.length === 0 || shouldSkipDrop(normalizedPaths)) {
    return;
  }

  await productStore.importFiles(normalizedPaths);
}

function triggerBackgroundRefresh() {
  if (document.visibilityState === "hidden") {
    return;
  }

  const store = productStore as typeof productStore & {
    backendStatus?: "checking" | "online" | "offline";
    initialize?: () => Promise<void>;
    refreshProductsSilently?: () => Promise<boolean>;
  };

  if (store.backendStatus !== "online") {
    if (typeof store.initialize === "function") {
      void store.initialize();
    }
    return;
  }

  if (typeof store.refreshProductsSilently !== "function") {
    return;
  }

  void store.refreshProductsSilently();
}

defineExpose({ showOnboarding });

onMounted(async () => {
  try {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    const currentWindow = getCurrentWindow();

    const unlistenDragDrop = await currentWindow.onDragDropEvent(async (event) => {
      switch (event.payload.type) {
        case "enter":
        case "over":
          isDragging.value = true;
          break;
        case "drop":
          await handleFilesDropped(event.payload.paths ?? []);
          break;
        case "leave":
          isDragging.value = false;
          break;
      }
    });
    unlisteners.push(unlistenDragDrop);
  } catch (error) {
    console.warn("Drag-and-drop listeners are unavailable outside Tauri.", error);
  }

  await productStore.initialize();

  window.addEventListener("focus", triggerBackgroundRefresh);
  document.addEventListener("visibilitychange", triggerBackgroundRefresh);
  unlisteners.push(() => window.removeEventListener("focus", triggerBackgroundRefresh));
  unlisteners.push(() =>
    document.removeEventListener("visibilitychange", triggerBackgroundRefresh)
  );

  productSyncTimer = window.setInterval(() => {
    triggerBackgroundRefresh();
  }, PRODUCT_SYNC_INTERVAL_MS);
});

onUnmounted(() => {
  if (productSyncTimer !== null) {
    window.clearInterval(productSyncTimer);
    productSyncTimer = null;
  }
  unlisteners.forEach((unlisten) => unlisten());
});
</script>

<template>
  <div class="app-container">
    <transition name="fade">
      <div
        v-if="productStore.backendStatus === 'offline'"
        class="backend-warning"
      >
        <span>后端服务未运行，部分功能不可用</span>
        <button @click="productStore.initialize()">重试连接</button>
      </div>
    </transition>

    <router-view />

    <transition name="fade">
      <div v-if="isDragging" class="drag-overlay" aria-hidden="true">
        <div class="drag-content">
          <div class="drag-icon">拖入</div>
          <div class="drag-text">释放以导入文件夹</div>
          <div class="drag-hint">支持将商品文件夹拖入当前窗口</div>
        </div>
      </div>
    </transition>

    <OnboardingGuide ref="onboardingRef" />
  </div>
</template>

<style lang="scss">
.app-container {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: var(--background-gradient);
  position: relative;
}

.backend-warning {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  background: linear-gradient(135deg, #ff6b6b, #ff8787);
  color: white;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  font-size: 14px;
  z-index: 9999;
  box-shadow: 0 2px 8px rgba(255, 107, 107, 0.3);

  button {
    background: rgba(255, 255, 255, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.4);
    color: white;
    padding: 4px 12px;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s ease;

    &:hover {
      background: rgba(255, 255, 255, 0.3);
    }
  }
}

.drag-overlay {
  position: fixed;
  inset: 0;
  background: rgba(92, 124, 250, 0.95);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
  backdrop-filter: blur(8px);
  pointer-events: none;
}

.drag-content {
  text-align: center;
  color: white;
  pointer-events: none;
}

.drag-icon {
  font-size: 40px;
  font-weight: 700;
  letter-spacing: 0.2em;
  margin-bottom: 24px;
  animation: bounce 1s ease infinite;
}

.drag-text {
  font-size: 28px;
  font-weight: 600;
  margin-bottom: 12px;
}

.drag-hint {
  font-size: 16px;
  opacity: 0.8;
}

@keyframes bounce {
  0%,
  100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
