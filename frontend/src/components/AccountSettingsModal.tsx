"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { type SettingsTab, useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { User as UserIcon, MonitorCog, Shield, Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import AccountSessionsSection from "./account-settings/AccountSessionsSection";
import MyAccountSection from "./account-settings/MyAccountSection";
import MixBalancerSection from "./account-settings/MixBalancerSection";
import FavoritesSection from "./account-settings/FavoritesSection";
import { useRouter, useSearchParams } from "next/navigation";

const TAB_CONFIG: { id: SettingsTab; icon: ReactNode }[] = [
  { id: "profile", icon: <UserIcon className="w-4 h-4" aria-hidden /> },
  { id: "preferences", icon: <MonitorCog className="w-4 h-4" aria-hidden /> },
  { id: "favorites", icon: <Star className="w-4 h-4" aria-hidden /> },
  { id: "sessions", icon: <Shield className="w-4 h-4" aria-hidden /> },
];

const PANEL_CLASS =
  "mt-0 space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500 focus-visible:outline-none";
const HEADING_CLASS = "text-xl font-semibold tracking-tight text-[color:var(--aqt-fg)]";
const SUBHEADING_CLASS = "mt-1 text-sm text-[color:var(--aqt-fg-muted)]";

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
    const matchedTab = TAB_CONFIG.find((tab) => tab.id === resolvedTab);
    if (matchedTab) {
      open(matchedTab.id);

      // Clean up URL without reloading
      const url = new URL(window.location.href);
      url.searchParams.delete("settings");
      window.history.replaceState({}, "", url.toString());
    }
  }, [searchParams, open, router]);

  return (
    <Dialog open={isOpen} onOpenChange={(openState) => !openState && close()}>
      {/* The dialog primitive's own close button is kept: it is translated,
          focus-ringed and present at every breakpoint. The bespoke replacement
          this file used to hoist in its place had no accessible name on mobile —
          its only text was an "Esc" hint hidden below `md`. */}
      <DialogContent className="flex h-[100dvh] max-h-[100dvh] w-full max-w-none flex-col gap-0 overflow-hidden rounded-none border-border/40 p-0 liquid-glass md:h-[80vh] md:max-h-none md:min-h-[600px] md:max-w-5xl md:rounded-2xl">
        <DialogTitle className="sr-only">{t("title")}</DialogTitle>

        <Tabs
          value={activeTab}
          onValueChange={(value) => {
            const tab = TAB_CONFIG.find((entry) => entry.id === value);
            if (tab) setActiveTab(tab.id);
          }}
          orientation="vertical"
          className="flex min-h-0 flex-1 flex-col md:flex-row"
        >
          {/* Sidebar — a left column on desktop, a horizontal tab strip on mobile */}
          <div className="shrink-0 border-b border-border/40 bg-[color:var(--aqt-overlay-1)] md:flex md:w-1/3 md:max-w-[280px] md:flex-col md:items-end md:border-b-0 md:pb-8 md:pt-14">
            <div className="w-full px-3 py-3 md:max-w-[220px] md:space-y-1 md:py-0">
              <h2 className="hidden px-3 pb-2 text-xs font-bold uppercase tracking-wider text-[color:var(--aqt-fg-muted)] md:block">
                {t("sidebarHeading")}
              </h2>
              {/* pr-14 on mobile keeps the last tab from scrolling under the close button */}
              <TabsList className="flex h-auto justify-start gap-1 overflow-x-auto rounded-none bg-transparent p-0 pr-14 md:flex-col md:overflow-visible md:pr-0">
                {TAB_CONFIG.map((tab) => (
                  <TabsTrigger
                    key={tab.id}
                    value={tab.id}
                    className={cn(
                      "flex shrink-0 items-center justify-start gap-2 whitespace-nowrap rounded-md px-3 py-2 text-left text-sm",
                      "text-[color:var(--aqt-fg-muted)] transition-all hover:bg-[color:var(--aqt-overlay-2)] hover:text-[color:var(--aqt-fg)]",
                      "data-[state=active]:bg-[color:var(--aqt-overlay-3)] data-[state=active]:font-medium data-[state=active]:text-[color:var(--aqt-fg)] data-[state=active]:shadow-none",
                      "md:w-full md:gap-3"
                    )}
                  >
                    {tab.icon}
                    {t(`tabs.${tab.id}`)}
                  </TabsTrigger>
                ))}
              </TabsList>

              <hr className="my-4 hidden border-t border-border/40 md:block" />
            </div>
          </div>

          {/* Content Area */}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-transparent">
            <div className="w-full flex-1 overflow-y-auto px-4 pb-12 pt-8 sm:px-8 md:pb-20 md:pt-14 xl:px-16">
              <div className="max-w-2xl">
                <TabsContent value="profile" className={PANEL_CLASS}>
                  <div>
                    <h3 className={HEADING_CLASS}>{t("profile.title")}</h3>
                    <p className={SUBHEADING_CLASS}>{t("profile.desc")}</p>
                  </div>
                  <MyAccountSection />
                </TabsContent>

                <TabsContent value="preferences" className={PANEL_CLASS}>
                  <div>
                    <h3 className={HEADING_CLASS}>{t("preferences.title")}</h3>
                    <p className={SUBHEADING_CLASS}>{t("preferences.desc")}</p>
                  </div>
                  <MixBalancerSection />
                </TabsContent>

                <TabsContent value="favorites" className={PANEL_CLASS}>
                  <div>
                    <h3 className={HEADING_CLASS}>{t("favorites.title")}</h3>
                    <p className={SUBHEADING_CLASS}>{t("favorites.desc")}</p>
                  </div>
                  <FavoritesSection />
                </TabsContent>

                <TabsContent value="sessions" className={PANEL_CLASS}>
                  <div>
                    <h3 className={HEADING_CLASS}>{t("sessions.title")}</h3>
                    <p className={SUBHEADING_CLASS}>{t("sessions.desc")}</p>
                  </div>
                  <AccountSessionsSection />
                </TabsContent>
              </div>
            </div>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
};

export default AccountSettingsModal;
