"use client";

import React, { createContext, useCallback, useContext, useMemo, useRef } from "react";

type AuraVars = {
  a: string; // "r g b"
  b: string; // "r g b"
  c: string; // "r g b"
};

type LiquidGlassContextValue = {
  setAura: (next: Partial<AuraVars>) => void;
};

const LiquidGlassContext = createContext<LiquidGlassContextValue | null>(null);

export function useLiquidGlass() {
  const ctx = useContext(LiquidGlassContext);
  if (!ctx) {
    throw new Error("useLiquidGlass must be used within UserLiquidGlassProvider");
  }
  return ctx;
}

const DEFAULT_AURA: AuraVars = {
  a: "34 197 94",
  b: "56 189 248",
  c: "245 158 11"
};

export interface UserLiquidGlassProviderProps {
  children: React.ReactNode;
}

const UserLiquidGlassProvider = ({ children }: UserLiquidGlassProviderProps) => {
  const rootRef = useRef<HTMLDivElement | null>(null);

  const setAura = useCallback((next: Partial<AuraVars>) => {
    const root = rootRef.current;
    if (!root) {
      return;
    }

    if (next.a) {
      root.style.setProperty("--lg-a", next.a);
    }
    if (next.b) {
      root.style.setProperty("--lg-b", next.b);
    }
    if (next.c) {
      root.style.setProperty("--lg-c", next.c);
    }
  }, []);

  const value = useMemo<LiquidGlassContextValue>(() => ({ setAura }), [setAura]);

  return (
    <LiquidGlassContext.Provider value={value}>
      <div
        ref={rootRef}
        className="liquid-glass relative"
        style={
          {
            "--lg-a": DEFAULT_AURA.a,
            "--lg-b": DEFAULT_AURA.b,
            "--lg-c": DEFAULT_AURA.c
          } as React.CSSProperties
        }
      >
        {children}
      </div>
    </LiquidGlassContext.Provider>
  );
};

export default UserLiquidGlassProvider;
