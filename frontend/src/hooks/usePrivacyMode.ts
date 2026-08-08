import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "vibe-privacy-mode";

function readStoredPrivacyMode() {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(STORAGE_KEY) === "1";
}

function applyPrivacyMode(enabled: boolean) {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.privacyMode = enabled ? "true" : "false";
}

export function usePrivacyMode() {
  const [enabled, setEnabled] = useState(readStoredPrivacyMode);

  useEffect(() => {
    applyPrivacyMode(enabled);
    window.localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
  }, [enabled]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== STORAGE_KEY) return;
      const next = event.newValue === "1";
      setEnabled(next);
      applyPrivacyMode(next);
    };

    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const toggle = useCallback(() => setEnabled((value) => !value), []);

  return { enabled, toggle };
}
