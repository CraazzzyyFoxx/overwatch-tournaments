"use client";

import type { CSSProperties, ReactNode } from "react";
import { useEffect } from "react";
import { type SettingsTab, useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { User as UserIcon, X, MonitorCog, Shield } from "lucide-react";
import { useTranslations } from "next-intl";
import AccountSessionsSection from "./account-settings/AccountSessionsSection";
import MyAccountSection from "./account-settings/MyAccountSection";
import { useRouter, useSearchParams } from "next/navigation";

const TAB_CONFIG: { id: SettingsTab; icon: ReactNode }[] = [
  { id: "profile", icon: <UserIcon className="w-4 h-4" /> },
  { id: "preferences", icon: <MonitorCog className="w-4 h-4" /> },
  { id: "sessions", icon: <Shield className="w-4 h-4" /> },
];

const AccountSettingsModal = () => {
  const t = useTranslations("accountSettings");
  const { isOpen, close, activeTab, setActiveTab, open } = useAccountSettingsModalStore();
  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    // Auto-open modal if URL has ?settings=... parameter (e.g. returning from OAuth)
    const settingsTab = searchParams.get("settings");
    if (settingsTab === "api-keys") {
      router.replace("/admin/access/api-keys");
      return;
    }
    // Back-compat: the standalone "connections" tab was merged into "My Account".
    // Keep stale bookmarks and in-flight OAuth `next` redirects working.
    const resolvedTab = settingsTab === "connections" ? "profile" : settingsTab;
    if (resolvedTab && TAB_CONFIG.some(t => t.id === resolvedTab)) {
      open(resolvedTab as SettingsTab);

      // Clean up URL without reloading
      const url = new URL(window.location.href);
      url.searchParams.delete("settings");
      window.history.replaceState({}, "", url.toString());
    }
  }, [searchParams, open, router]);

  return (
    <Dialog open={isOpen} onOpenChange={(openState) => !openState && close()}>
      {/* Hide the default close button injected by dialog primitive using [&>button]:hidden */}
        <DialogContent
        className="w-full max-w-none h-[100dvh] max-h-[100dvh] rounded-none p-0 gap-0 overflow-hidden border-border/40 liquid-glass flex flex-col [&>button]:hidden md:max-w-5xl md:h-[80vh] md:max-h-none md:min-h-[600px] md:flex-row md:rounded-2xl"
        style={{
          "--lg-a": "15 23 42", // deep slate
          "--lg-b": "56 189 248", // light blue
          "--lg-c": "139 92 246", // purple
        } as CSSProperties}
      >
        <DialogTitle className="sr-only">{t("title")}</DialogTitle>

        {/* Close button — anchored to the dialog's top-right in both layouts (DialogContent
            is the positioned ancestor), so it stays pinned on the mobile full-screen sheet. */}
        <div className="absolute top-3 right-3 md:top-6 md:right-8 z-30">
          <button
            onClick={close}
            className="group flex flex-col items-center gap-1 text-slate-400 hover:text-white transition-colors"
          >
            <div className="p-2 rounded-full border border-slate-700 group-hover:bg-white/10 transition-colors">
              <X className="w-5 h-5" />
            </div>
            <span className="hidden md:inline text-[10px] font-bold uppercase tracking-widest">Esc</span>
          </button>
        </div>

        {/* Sidebar — a left column on desktop, a horizontal tab strip on mobile */}
        <div className="relative z-10 shrink-0 bg-black/10 border-b border-white/10 md:border-b-0 md:w-1/3 md:max-w-[280px] md:pt-14 md:pb-8 md:flex md:flex-col md:items-end">
          <div className="w-full md:max-w-[220px] px-3 py-3 md:py-0 md:space-y-1">
            <h2 className="hidden md:block px-3 pb-2 text-xs font-bold text-slate-400 uppercase tracking-wider">
              {t("sidebarHeading")}
            </h2>
            {/* pr-14 on mobile keeps the last tab from scrolling under the hoisted close button */}
            <div className="flex gap-1 overflow-x-auto pr-14 md:flex-col md:overflow-visible md:pr-0">
              {TAB_CONFIG.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex shrink-0 items-center gap-2 md:gap-3 whitespace-nowrap px-3 py-2 rounded-md text-sm transition-all text-left md:w-full ${
                    activeTab === tab.id
                      ? "bg-white/10 text-white font-medium"
                      : "text-slate-300 hover:bg-white/5 hover:text-white"
                  }`}
                >
                  {tab.icon}
                  {t(`tabs.${tab.id}`)}
                </button>
              ))}
            </div>

            <hr className="hidden md:block border-t border-white/10 my-4" />
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 min-h-0 relative z-10 flex flex-col overflow-hidden bg-transparent">
          <div className="flex-1 overflow-y-auto w-full pt-8 md:pt-14 pb-12 md:pb-20 px-4 sm:px-8 xl:px-16">
            <div className="max-w-2xl">
              {activeTab === "profile" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-white">{t("profile.title")}</h3>
                    <p className="text-sm text-slate-400 mt-1">{t("profile.desc")}</p>
                  </div>
                  <MyAccountSection />
                </div>
              )}

              {activeTab === "preferences" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-white">{t("preferences.title")}</h3>
                    <p className="text-sm text-slate-400 mt-1">{t("preferences.desc")}</p>
                  </div>
                  <div className="flex flex-col items-center justify-center py-20 text-slate-500 border border-dashed border-white/10 rounded-xl">
                    <MonitorCog className="w-12 h-12 mb-4 opacity-50" />
                    <p>{t("preferences.comingSoon")}</p>
                  </div>
                </div>
              )}

              {activeTab === "sessions" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-white">{t("sessions.title")}</h3>
                    <p className="text-sm text-slate-400 mt-1">{t("sessions.desc")}</p>
                  </div>
                  <AccountSessionsSection />
                </div>
              )}
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
};

export default AccountSettingsModal;
