<script setup lang="ts">
import { computed, onUnmounted, watch, ref, nextTick } from "vue";

const props = defineProps<{
  visible: boolean;
  position: { x: number; y: number };
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "action", action: string): void;
}>();

const menuRef = ref<HTMLElement | null>(null);

// 计算菜单位置，防止超出屏幕
const menuStyle = computed(() => {
  if (!props.visible) return {};
  
  const menuWidth = 120; // 菜单宽度
  const menuHeight = 80; // 菜单高度（估算）
  const padding = 10; // 边距
  
  let x = props.position.x;
  let y = props.position.y;
  
  // 防止超出右边界
  if (x + menuWidth + padding > window.innerWidth) {
    x = window.innerWidth - menuWidth - padding;
  }
  
  // 防止超出下边界
  if (y + menuHeight + padding > window.innerHeight) {
    y = window.innerHeight - menuHeight - padding;
  }
  
  // 防止超出左边界
  if (x < padding) {
    x = padding;
  }
  
  // 防止超出上边界
  if (y < padding) {
    y = padding;
  }
  
  return {
    left: x + 'px',
    top: y + 'px',
  };
});

// 关闭菜单
function closeMenu() {
  emit("update:visible", false);
}

// 处理点击
function handleAction(action: string) {
  emit("action", action);
  closeMenu();
}

// 点击外部关闭
function handleClickOutside(event: MouseEvent) {
  const target = event.target as HTMLElement;
  if (menuRef.value && !menuRef.value.contains(target)) {
    closeMenu();
  }
}

// 按ESC关闭
function handleKeydown(event: KeyboardEvent) {
  if (event.key === "Escape") {
    closeMenu();
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      // 延迟添加事件监听，避免立即触发点击事件
      nextTick(() => {
        document.addEventListener("click", handleClickOutside, true);
        document.addEventListener("keydown", handleKeydown);
      });
    } else {
      document.removeEventListener("click", handleClickOutside, true);
      document.removeEventListener("keydown", handleKeydown);
    }
  }
);

onUnmounted(() => {
  document.removeEventListener("click", handleClickOutside, true);
  document.removeEventListener("keydown", handleKeydown);
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      ref="menuRef"
      class="context-menu"
      :style="menuStyle"
      @contextmenu.prevent
    >
      <ul>
        <li @click="handleAction('open')">
          <span class="menu-icon">📂</span>
          <span>打开</span>
        </li>
        <li @click="handleAction('delete')">
          <span class="menu-icon">🗑️</span>
          <span>删除</span>
        </li>
      </ul>
    </div>
  </Teleport>
</template>

<style lang="scss" scoped>
.context-menu {
  position: fixed;
  background: #fff;
  border: 1px solid #ccc;
  padding: 5px 0;
  box-shadow: 2px 2px 5px rgba(0, 0, 0, 0.2);
  z-index: 1000;
  min-width: 120px;

  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  li {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 15px;
    cursor: pointer;
    font-size: var(--font-size-base);
    color: var(--text-primary);
    border-top: solid 1px #f0f0f0;
    transition: background-color 0.2s ease;

    &:first-child {
      border-top: none;
    }

    &:hover {
      background: rgba(92, 124, 250, 0.08);
      color: var(--primary-color);
    }
  }

  .menu-icon {
    font-size: 14px;
  }
}
</style>
