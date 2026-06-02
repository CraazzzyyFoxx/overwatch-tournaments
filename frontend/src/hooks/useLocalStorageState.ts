"use client";

import { useSyncExternalStore, useCallback } from "react";

const listeners = new Set<() => void>();

function subscribe(callback: () => void) {
  listeners.add(callback);
  
  if (typeof window !== "undefined") {
    window.addEventListener("storage", callback);
  }
  
  return () => {
    listeners.delete(callback);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", callback);
    }
  };
}

function notifyListeners() {
  for (const listener of listeners) {
    listener();
  }
}

export function useLocalStorageState<T>(
  key: string,
  defaultValue: T,
): [T, (value: T | ((val: T) => T)) => void] {
  const getSnapshot = useCallback(() => {
    if (typeof window === "undefined") return JSON.stringify(defaultValue);
    try {
      const item = localStorage.getItem(key);
      return item !== null ? item : JSON.stringify(defaultValue);
    } catch {
      return JSON.stringify(defaultValue);
    }
  }, [key, defaultValue]);

  const getServerSnapshot = useCallback(() => {
    return JSON.stringify(defaultValue);
  }, [defaultValue]);

  const rawValue = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const value = JSON.parse(rawValue) as T;

  const setValue = useCallback(
    (newValue: T | ((val: T) => T)) => {
      try {
        const nextValue = newValue instanceof Function ? newValue(value) : newValue;
        localStorage.setItem(key, JSON.stringify(nextValue));
        notifyListeners();
      } catch (error) {
        console.warn(`Error setting localStorage key "${key}":`, error);
      }
    },
    [key, value],
  );

  return [value, setValue];
}
