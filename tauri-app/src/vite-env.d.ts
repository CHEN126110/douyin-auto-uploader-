/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<{}, {}, any>;
  export default component;
}

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __APP_VERSION__: string;
