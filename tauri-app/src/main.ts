import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import * as ElementPlusIconsVue from "@element-plus/icons-vue";
// @ts-ignore - element-plus locale module
import zhCn from "element-plus/dist/locale/zh-cn.mjs";
import "element-plus/dist/index.css";
import "./styles/variables.scss";
import "./styles/global.scss";
import "./styles/components.scss";
import App from "./App.vue";
import router from "./router";

const showFatal = (title: string, detail: unknown) => {
  const root = document.getElementById("app");
  const message =
    detail instanceof Error
      ? `${detail.name}: ${detail.message}\n${detail.stack ?? ""}`
      : String(detail);
  if (root) {
    root.innerHTML = `<div style="padding:16px;font-family:Consolas,monospace;color:#b00020;white-space:pre-wrap;">${title}\n${message}</div>`;
  } else {
    document.body.innerHTML = `<div style="padding:16px;font-family:Consolas,monospace;color:#b00020;white-space:pre-wrap;">${title}\n${message}</div>`;
  }
};

const isIgnorablePromiseRejection = (reason: unknown) => {
  if (reason === "cancel" || reason === "close") {
    return true;
  }

  if (typeof reason === "object" && reason !== null && "action" in reason) {
    const action = (reason as { action?: unknown }).action;
    return action === "cancel" || action === "close";
  }

  return false;
};

window.addEventListener("error", (event) => {
  showFatal("前端运行错误", event.error ?? event.message);
});

window.addEventListener("unhandledrejection", (event) => {
  if (isIgnorablePromiseRejection(event.reason)) {
    event.preventDefault();
    return;
  }

  showFatal("前端 Promise 异常", event.reason);
});

const app = createApp(App);

// 注册所有Element Plus图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component);
}

try {
  app.use(createPinia());
  app.use(router);
  app.use(ElementPlus, {
    locale: zhCn,
    size: "default",
  });
  app.mount("#app");
} catch (error) {
  showFatal("应用初始化失败", error);
}
