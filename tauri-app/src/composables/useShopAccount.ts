import { ref } from "vue";
import { useProductStore } from "@/stores/productStore";
import type ShopStatusBar from "@/components/ShopStatusBar.vue";
import type { ShopSessionState } from "@/types";

/**
 * 主页的「当前账户」绑定：账户栏（ShopStatusBar）读到的店铺会话同步进 store，
 * 发布流程要靠它判断平台、确认店铺，并在账户栏忙的时候等一等。
 */
export function useShopAccount() {
  const productStore = useProductStore();

  const shopStatusBarRef = ref<InstanceType<typeof ShopStatusBar> | null>(null);
  const shopSession = ref<ShopSessionState | null>(null);
  // 账户栏正在处理账户（切换 / 添加 / 刷新）：这时不能开始发布
  const shopAccountBusy = ref(false);

  function handleShopSessionChanged(state: ShopSessionState | null) {
    shopSession.value = state;
    productStore.setShopSession(state);
  }

  return { shopStatusBarRef, shopSession, shopAccountBusy, handleShopSessionChanged };
}
