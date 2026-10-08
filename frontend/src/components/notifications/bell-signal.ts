import { create } from "zustand";

/**
 * Whether the header's notification panel is open.
 *
 * Shared state rather than the bell's own `useState`, because the floating
 * stack's "Ещё N" sits in a different subtree and has to open the same panel.
 */
export const useBellSignal = create<{ open: boolean; setOpen: (open: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => set({ open })
}));
