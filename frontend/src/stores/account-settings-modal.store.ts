import { create } from "zustand";

export type SettingsTab = "connections" | "profile" | "preferences" | "sessions";

type AccountSettingsModalStore = {
  isOpen: boolean;
  activeTab: SettingsTab;
  open: (tab?: SettingsTab) => void;
  close: () => void;
  setActiveTab: (tab: SettingsTab) => void;
};

export const useAccountSettingsModalStore = create<AccountSettingsModalStore>((set) => ({
  isOpen: false,
  activeTab: "connections",
  open: (tab = "connections") => set({ isOpen: true, activeTab: tab }),
  close: () => set({ isOpen: false }),
  setActiveTab: (tab) => set({ activeTab: tab })
}));
