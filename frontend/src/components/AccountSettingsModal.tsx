"use client";

import type { CSSProperties, ReactNode } from "react";
import { useEffect } from "react";
import { type SettingsTab, useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Link2, User as UserIcon, X, MonitorCog, Shield } from "lucide-react";
import AccountConnectionsSection from "./account-settings/AccountConnectionsSection";
import AccountSessionsSection from "./account-settings/AccountSessionsSection";
import { useRouter, useSearchParams } from "next/navigation";

const TAB_CONFIG: { id: SettingsTab; label: string; icon: ReactNode }[] = [
  { id: "profile", label: "My Account", icon: <UserIcon className="w-4 h-4" /> },
  { id: "preferences", label: "Preferences", icon: <MonitorCog className="w-4 h-4" /> },
  { id: "connections", label: "Connections", icon: <Link2 className="w-4 h-4" /> },
  { id: "sessions", label: "Sessions", icon: <Shield className="w-4 h-4" /> },
];

const AccountSettingsModal = () => {
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
    if (settingsTab && TAB_CONFIG.some(t => t.id === settingsTab)) {
      open(settingsTab as SettingsTab);
      
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
        className="max-w-5xl h-[80vh] min-h-[600px] p-0 overflow-hidden border-border/40 sm:rounded-2xl liquid-glass flex flex-row [&>button]:hidden"
        style={{
          "--lg-a": "15 23 42", // deep slate
          "--lg-b": "56 189 248", // light blue
          "--lg-c": "139 92 246", // purple
        } as CSSProperties}
      >
        <DialogTitle className="sr-only">Account Settings</DialogTitle>

        {/* Sidebar */}
        <div className="w-1/3 max-w-[280px] pt-14 pb-8 flex flex-col items-end relative z-10 bg-black/10">
          <div className="w-full max-w-[220px] px-3 space-y-1">
            <h2 className="px-3 pb-2 text-xs font-bold text-slate-400 uppercase tracking-wider">
              User Settings
            </h2>
            {TAB_CONFIG.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-all text-left ${
                  activeTab === tab.id 
                    ? "bg-white/10 text-white font-medium" 
                    : "text-slate-300 hover:bg-white/5 hover:text-white"
                }`}
              >
                {tab.icon}
                {tab.label}
              </button>
            ))}

            <hr className="border-t border-white/10 my-4" />
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 relative z-10 flex flex-col h-full overflow-hidden bg-transparent">
          {/* Close Button Header */}
          <div className="absolute top-6 right-8">
            <button 
              onClick={close} 
              className="group flex flex-col items-center gap-1 text-slate-400 hover:text-white transition-colors"
            >
              <div className="p-2 rounded-full border border-slate-700 group-hover:bg-white/10 transition-colors">
                <X className="w-5 h-5" />
              </div>
              <span className="text-[10px] font-bold uppercase tracking-widest">Esc</span>
            </button>
          </div>

          <div className="flex-1 overflow-y-auto w-full pt-14 pb-20 px-10 xl:px-16">
            <div className="max-w-2xl">
              {activeTab === "connections" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-white">Connections</h3>
                    <p className="text-sm text-slate-400 mt-1">Connect your accounts to unlock special integrations.</p>
                  </div>
                  <AccountConnectionsSection />
                </div>
              )}

              {activeTab === "profile" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-white">My Account</h3>
                    <p className="text-sm text-slate-400 mt-1">Manage your public profile and preferences.</p>
                  </div>
                  <div className="flex flex-col items-center justify-center py-20 text-slate-500 border border-dashed border-white/10 rounded-xl">
                    <UserIcon className="w-12 h-12 mb-4 opacity-50" />
                    <p>Profile settings coming soon</p>
                  </div>
                </div>
              )}

              {activeTab === "preferences" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-white">Preferences</h3>
                    <p className="text-sm text-slate-400 mt-1">Customize your tournament experience.</p>
                  </div>
                  <div className="flex flex-col items-center justify-center py-20 text-slate-500 border border-dashed border-white/10 rounded-xl">
                    <MonitorCog className="w-12 h-12 mb-4 opacity-50" />
                    <p>App preferences coming soon</p>
                  </div>
                </div>
              )}

              {activeTab === "sessions" && (
                <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                  <div>
                    <h3 className="text-xl font-semibold tracking-tight text-white">Sessions</h3>
                    <p className="text-sm text-slate-400 mt-1">
                      Review active logins, session history, and revoke access on other devices.
                    </p>
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
