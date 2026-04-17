import { invoke } from "@tauri-apps/api/core";

export const isTauriRuntime = (): boolean => {
  if (typeof window === "undefined") {
    return false;
  }
  return Boolean((window as Record<string, unknown>).__TAURI_INTERNALS__);
};

export const sidecarCall = async <T>(
  action: string,
  payload: Record<string, unknown> = {},
): Promise<T> => {
  if (!isTauriRuntime()) {
    throw new Error("Tauri runtime not detected. Start with `npm run tauri:dev`.");
  }
  return await invoke<T>("sidecar_call", {
    action,
    payloadJson: JSON.stringify(payload ?? {}),
  });
};
