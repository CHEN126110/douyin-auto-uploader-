import { createApp } from "vue";
import { createPinia } from "pinia";
// 函数式 API 样式：ElMessage/ElMessageBox/ElLoading 在代码里手写 import 调用，
// ElementPlusResolver 只对它自己生成的 import 注入样式，手写 import 的样式不会自动注入，
// 必须在此手动引入（项目未用 ElNotification）。组件样式由 unplugin-vue-components 按需注入。
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import "element-plus/es/components/loading/style/css";
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

const isIgnorableRuntimeError = (detail: unknown) => {
  const message =
    detail instanceof Error
      ? detail.message
      : typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && "message" in detail
          ? String((detail as { message?: unknown }).message ?? "")
          : "";

  return (
    message.includes("ResizeObserver loop completed with undelivered notifications") ||
    message.includes("ResizeObserver loop limit exceeded")
  );
};

window.addEventListener("error", (event) => {
  if (isIgnorableRuntimeError(event.error ?? event.message)) {
    event.preventDefault();
    return;
  }
  showFatal("前端运行错误", event.error ?? event.message);
});

window.addEventListener("unhandledrejection", (event) => {
  if (isIgnorablePromiseRejection(event.reason)) {
    event.preventDefault();
    return;
  }

  if (isIgnorableRuntimeError(event.reason)) {
    event.preventDefault();
    return;
  }

  showFatal("前端 Promise 异常", event.reason);
});

const app = createApp(App);

try {
  app.use(createPinia());
  app.use(router);
  app.mount("#app");
} catch (error) {
  showFatal("应用初始化失败", error);
}
