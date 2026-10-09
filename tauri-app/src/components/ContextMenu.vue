<script setup lang="ts">
import { computed, onUnmounted, watch, ref, nextTick } from "vue";
import { FolderOpened, Picture, Delete } from "@element-plus/icons-vue";

const props = defineProps<{
  visible: boolean;
  position: { x: number; y: number };
}>();

const emit = defineEmits<{
  (e: "update:visible", value: boolean): void;
  (e: "action", action: string): void;
}>();

const menuRef = ref<HTMLElement | null>(null);
const menuSize = ref({ width: 160, height: 146 });
let returnFocus: HTMLElement | null = null;

// 计算菜单位置，防止超出屏幕
const menuStyle = computed(() => {
  if (!props.visible) return {};
  
  const menuWidth = menuSize.value.width;
  const menuHeight = menuSize.value.height;
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
  if (returnFocus?.isConnected) returnFocus.focus();
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
    event.preventDefault();
    closeMenu();
  } else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
    const buttons = Array.from(menuRef.value?.querySelectorAll<HTMLButtonElement>("button") || []);
    if (!buttons.length) return;
    event.preventDefault();
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 :
      (index + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
    buttons[next].focus();
  }
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      returnFocus = document.activeElement as HTMLElement | null;
      // 延迟添加事件监听，避免立即触发点击事件
      nextTick(() => {
        if (!props.visible || !menuRef.value) return;
        const rect = menuRef.value.getBoundingClientRect();
        menuSize.value = { width: rect.width, height: rect.height };
        menuRef.value.querySelector<HTMLButtonElement>("button")?.focus();
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
      role="menu"
      aria-label="商品操作"
      :style="menuStyle"
      @contextmenu.prevent
    >
      <ul>
        <li><button type="button" role="menuitem" @click="handleAction('media')"><Picture class="menu-icon" /><span>商品图片</span></button></li>
        <li><button type="button" role="menuitem" @click="handleAction('open')"><FolderOpened class="menu-icon" /><span>打开文件夹</span></button></li>
        <li><button type="button" role="menuitem" @click="handleAction('delete')"><Delete class="menu-icon" /><span>删除商品</span></button></li>
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
  min-width: 160px;

  ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }

  button {
    border: 0;
    background: transparent;
    width: 100%;
    font: inherit;
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
    &:focus-visible { outline: 2px solid var(--primary-color); outline-offset: -2px; }
  }

  .menu-icon {
    width: 16px;
    height: 16px;
  }
}
</style>
