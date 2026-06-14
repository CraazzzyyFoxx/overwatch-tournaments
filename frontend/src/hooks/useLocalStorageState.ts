"use client";

import { useState, useEffect, useCallback } from "react";

export function useLocalStorageState<T>(
  key: string,
  defaultValue: T,
): [T, (value: T | ((val: T) => T)) => void] {
  const [state, setState] = useState<T>(defaultValue);

  // Load from localStorage on mount/key change
  useEffect(() => {
    try {
      const item = localStorage.getItem(key);
      if (item !== null) {
        const parsed = JSON.parse(item) as T;
        // Defer updating state to avoid synchronous rendering side-effects/warnings
        setTimeout(() => {
          setState(parsed);
        }, 0);
      }
    } catch (error) {
      console.warn(`Error reading localStorage key "${key}":`, error);
    }
  }, [key]);

  const setPersistedState = useCallback(
    (value: T | ((val: T) => T)) => {
      setState((prev) => {
        const next = value instanceof Function ? value(prev) : value;
        try {
          localStorage.setItem(key, JSON.stringify(next));
          // Dispatch storage event to notify other instances
          window.dispatchEvent(new Event("storage"));
        } catch (error) {
          console.warn(`Error setting localStorage key "${key}":`, error);
        }
        return next;
      });
    },
    [key],
  );

  // Subscribe to storage changes (e.g. from other tabs/windows)
  useEffect(() => {
    const handleStorageChange = () => {
      try {
        const item = localStorage.getItem(key);
        if (item !== null) {
          const parsed = JSON.parse(item) as T;
          setState(parsed);
        }
      } catch (error) {
        console.warn(`Error updating state from storage change for key "${key}":`, error);
      }
    };

    window.addEventListener("storage", handleStorageChange);
    return () => window.removeEventListener("storage", handleStorageChange);
  }, [key]);

  return [state, setPersistedState];
}
