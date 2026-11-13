"use client";

import { useEffect, useState } from "react";

const STORAGE_KEY = "aegis_demo_mode_enabled";

/**
 * Returns whether Demo Data mode is globally enabled.
 * Defaults to false (Strict Real Data Mode).
 */
export function isDemoModeEnabled(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const val = localStorage.getItem(STORAGE_KEY);
    return val === "true";
  } catch {
    return false;
  }
}

/**
 * Updates Demo Data mode state and dispatches a storage event for cross-component sync.
 */
export function setDemoModeEnabled(enabled: boolean): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? "true" : "false");
    window.dispatchEvent(new CustomEvent("aegis:demo-mode-change", { detail: { enabled } }));
  } catch {
    // Ignore storage errors in restricted contexts
  }
}

/**
 * React hook to read and toggle Demo Data mode with automatic sync across pages.
 */
export function useDemoMode(): [boolean, (val: boolean) => void] {
  const [enabled, setEnabled] = useState<boolean>(false);

  useEffect(() => {
    setEnabled(isDemoModeEnabled());

    const handleCustom = (e: Event) => {
      const custom = e as CustomEvent<{ enabled: boolean }>;
      if (custom.detail && typeof custom.detail.enabled === "boolean") {
        setEnabled(custom.detail.enabled);
      }
    };

    const handleStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) {
        setEnabled(e.newValue === "true");
      }
    };

    window.addEventListener("aegis:demo-mode-change", handleCustom);
    window.addEventListener("storage", handleStorage);
    return () => {
      window.removeEventListener("aegis:demo-mode-change", handleCustom);
      window.removeEventListener("storage", handleStorage);
    };
  }, []);

  const toggle = (val: boolean) => {
    setEnabled(val);
    setDemoModeEnabled(val);
  };

  return [enabled, toggle];
}

