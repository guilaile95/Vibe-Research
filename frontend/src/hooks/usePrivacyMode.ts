import { useCallback, useEffect, useSyncExternalStore } from "react";

const STORAGE_KEY = "vibe-privacy-mode";
const listeners = new Set<() => void>();
let cachedValue: boolean | null = null;
let listeningToStorage = false;

function readStoredPrivacyMode() {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STORAGE_KEY) === "1";
}

function getSnapshot() {
  if (cachedValue === null) cachedValue = readStoredPrivacyMode();
  return cachedValue;
}

function applyPrivacyMode(enabled: boolean) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.privacyMode = enabled ? "true" : "false";
}

function emit() {
  listeners.forEach((listener) => listener());
}

function setPrivacyMode(enabled: boolean, persist = true) {
  if (cachedValue === enabled) {
    applyPrivacyMode(enabled);
    return;
  }
  cachedValue = enabled;
  applyPrivacyMode(enabled);
  if (persist && typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
  }
  emit();
}

function onStorage(event: StorageEvent) {
  if (event.key !== STORAGE_KEY) return;
  setPrivacyMode(event.newValue === "1", false);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!listeningToStorage && typeof window !== "undefined") {
    window.addEventListener("storage", onStorage);
    listeningToStorage = true;
  }

  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && listeningToStorage && typeof window !== "undefined") {
      window.removeEventListener("storage", onStorage);
      listeningToStorage = false;
    }
  };
}

export function usePrivacyMode() {
  const enabled = useSyncExternalStore(subscribe, getSnapshot, () => false);

  useEffect(() => {
    applyPrivacyMode(enabled);
  }, [enabled]);

  const toggle = useCallback(() => setPrivacyMode(!getSnapshot()), []);

  return { enabled, toggle };
}
