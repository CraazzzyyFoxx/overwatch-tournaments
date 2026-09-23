"use client";

import type { ReactNode } from "react";
import { useEffect } from "react";
import { Bell, EyeOff, type LucideIcon, ShieldCheck, Shuffle, Star, User as UserIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { type SettingsTab, useAccountSettingsModalStore } from "@/stores/account-settings-modal.store";
import AccountSessionsSection from "./account-settings/AccountSessionsSection";
import DeleteAccountSection from "./account-settings/DeleteAccountSection";
import FavoritesSection from "./account-settings/FavoritesSection";
import MixBalancerSection from "./account-settings/MixBalancerSection";
import MyAccountSection from "./account-settings/MyAccountSection";
import NotificationsSection from "./account-settings/NotificationsSection";
import PrivacySection from "./account-settings/PrivacySection";

// Who you are, what others see of you, then who can act as you, then your own
// lists, then the host-only mix tooling. Account deletion lives with the
// sessions, not beside the avatar picker: it is the last word on access, not a
// profile edit.
const TABS: { id: SettingsTab; icon: LucideIcon; content: ReactNode }[] = [
  { id: "profile", icon: UserIcon, content: <MyAccountSection /> },
  { id: "privacy", icon: EyeOff, content: <PrivacySection /> },
  {
    id: "security",
    icon: ShieldCheck,
    content: (
      <>
        <AccountSessionsSection />
        <DeleteAccountSection />
      </>
    )
  },
  { id: "notifications", icon: Bell, content: <NotificationsSection /> },
  { id: "favorites", icon: Star, content: <FavoritesSection /> },
  { id: "mixes", icon: Shuffle, content: <MixBalancerSection /> }
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
    // Back-compat: the standalone "connections" tab was merged into the profile tab.
    // Keep stale bookmarks and in-flight OAuth `next` redirects working.
    const resolvedTab = settingsTab === "connections" ? "profile" : settingsTab;
    const matchedTab = TABS.find((tab) => tab.id === resolvedTab);
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
        <Tabs
          value={activeTab}
          onValueChange={(value) => {
            const tab = TABS.find((entry) => entry.id === value);
            if (tab) setActiveTab(tab.id);
          }}
          orientation="vertical"
          className="flex min-h-0 flex-1 flex-col md:flex-row"
        >
          {/* Sidebar — a left column on desktop, a horizontal tab strip on mobile */}
          <div className="shrink-0 border-b border-border/40 bg-[color:var(--aqt-overlay-1)] md:flex md:w-1/3 md:max-w-[280px] md:flex-col md:items-end md:border-b-0 md:pb-8 md:pt-14">
            <div className="w-full px-3 py-3 md:max-w-[220px] md:py-0">
              {/* The one visible title; below `md` the tab strip is the chrome. */}
              <DialogTitle className="sr-only text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)] md:not-sr-only md:block md:px-3 md:pb-3">
                {t("title")}
              </DialogTitle>
              {/* pr-14 on mobile keeps the last tab from scrolling under the close button */}
              <TabsList className="flex h-auto justify-start gap-1 overflow-x-auto rounded-none bg-transparent p-0 pr-14 md:flex-col md:overflow-visible md:pr-0">
                {TABS.map(({ id, icon: Icon }) => (
                  <TabsTrigger
                    key={id}
                    value={id}
                    className={cn(
                      "flex shrink-0 items-center justify-start gap-2 whitespace-nowrap rounded-md px-3 py-2 text-left text-sm",
                      "text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-2)] hover:text-[color:var(--aqt-fg)]",
                      "data-[state=active]:bg-[color:var(--aqt-overlay-3)] data-[state=active]:font-medium data-[state=active]:text-[color:var(--aqt-fg)] data-[state=active]:shadow-none",
                      "md:w-full md:gap-3"
                    )}
                  >
                    <Icon className="size-4" aria-hidden />
                    {t(`tabs.${id}`)}
                  </TabsTrigger>
                ))}
              </TabsList>
            </div>
          </div>

          {/* Content Area */}
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-transparent">
            <div className="w-full flex-1 overflow-y-auto px-4 pb-12 pt-8 sm:px-8 md:pb-20 md:pt-14 xl:px-16">
              <div className="max-w-2xl">
                {TABS.map(({ id, content }) => (
                  <TabsContent key={id} value={id} className="mt-0 space-y-8 focus-visible:outline-none">
                    <div className="space-y-1">
                      <h3 className="text-title font-semibold text-[color:var(--aqt-fg)]">
                        {t(`${id}.title`)}
                      </h3>
                      <p className="text-body text-pretty text-[color:var(--aqt-fg-muted)]">
                        {t(`${id}.desc`)}
                      </p>
                    </div>
                    {content}
                  </TabsContent>
                ))}
              </div>
            </div>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
};

export default AccountSettingsModal;
