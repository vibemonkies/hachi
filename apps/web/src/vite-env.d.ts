/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_HACHI_API_BASE_URL?: string;
  readonly VITE_HACHI_REPLAY_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
