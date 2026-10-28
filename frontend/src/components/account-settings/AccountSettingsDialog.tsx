"use client";

import { useEffect, useRef, type ReactNode } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  ArrowUpRight,
  Bell,
  ChevronRight,
  EyeOff,
  type LucideIcon,
  ScrollText,
  ShieldCheck,
  Shuffle,
  Star,
  User as UserIcon
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { getAuthProfileHref } from "@/lib/auth/profile-links";
import { cn } from "@/lib/utils";
import {
  type SettingsTab,
  useAccountSettingsModalStore
} from "@/stores/account-settings-modal.store";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import AccountSessionsSection from "./AccountSessionsSection";
import DeleteAccountSection from "./DeleteAccountSection";
import FavoritesSection from "./FavoritesSection";
import { LogDirectorySection } from "./LogDirectorySection";
import MixBalancerSection from "./MixBalancerSection";
import MyAccountSection from "./MyAccountSection";
import NotificationsSection from "./NotificationsSection";
import PrivacySection from "./PrivacySection";

// Who you are, what others see of you, who can act as you and what reaches
// you; then your own lists and the host tooling. Account deletion lives with
// the sessions, not beside the avatar picker: it is the last word on access,
// not a profile edit.
const RAIL: { group: "account" | "personal"; tabs: { id: SettingsTab; icon: LucideIcon }[] }[] = [
  {
    group: "account",
    tabs: [
      { id: "profile", icon: UserIcon },
      { id: "privacy", icon: EyeOff },
      { id: "security", icon: ShieldCheck },
      { id: "notifications", icon: Bell }
    ]
  },
  {
    group: "personal",
    tabs: [
      { id: "favorites", icon: Star },
      { id: "mixes", icon: Shuffle },
      { id: "logs", icon: ScrollText }
    ]
  }
];

const PANELS: Record<SettingsTab, ReactNode> = {
  profile: <MyAccountSection />,
  privacy: <PrivacySection />,
  security: (
    <div className="space-y-6">
      <AccountSessionsSection />
      <DeleteAccountSection />
    </div>
  ),
  notifications: <NotificationsSection />,
  favorites: <FavoritesSection />,
  mixes: <MixBalancerSection />,
  logs: <LogDirectorySection />
};

/**
 * Loaded on the first open by the `AccountSettingsModal` gate, so the sections
 * and their services stay out of every route's first-load bundle.
 *
 * From `md` the section rail and the open section sit side by side. Below it
 * the dialog drills in: the rail is the whole screen until a section opens,
 * and the section's back arrow returns to it (`sectionOpen` in the store).
 */
const AccountSettingsDialog = () => {
  const t = useTranslations("accountSettings");
  const { isOpen, close, activeTab, setActiveTab, sectionOpen, showSections } =
    useAccountSettingsModalStore();
  const profileHref = getAuthProfileHref(useAuthProfileStore((state) => state.user));
  const isPhone = !useMediaQuery("(min-width: 768px)", true);
  const railRef = useRef<HTMLDivElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);

  // Drilling in or back hides the element that had focus: hand it to the
  // section's heading, or back to the row that opened the section. A frame
  // later, because Radix picks a tab on mousedown, and the browser's own
  // focus of the (by then hidden) row lands on the dialog right after it.
  const shownSection = useRef(sectionOpen);
  useEffect(() => {
    if (shownSection.current === sectionOpen) return;
    shownSection.current = sectionOpen;
    if (!isPhone) return;
    const frame = requestAnimationFrame(() => {
      if (sectionOpen) headingRef.current?.focus();
      else railRef.current?.querySelector<HTMLElement>('[role="tab"][data-state="active"]')?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [sectionOpen, isPhone]);

  return (
    <Dialog open={isOpen} onOpenChange={(openState) => !openState && close()}>
      {/* The section heading and its one-line description are the visible
          context; there is no separate dialog description. */}
      <DialogContent
        variant="panel"
        aria-describedby={undefined}
        className="h-[100dvh] max-h-[100dvh] w-full max-w-none rounded-none border-0 md:h-[min(85dvh,760px)] md:max-h-[calc(100dvh-2rem)] md:w-[calc(100%-2rem)] md:max-w-5xl md:rounded-xl md:border"
      >
        <Tabs
          value={activeTab}
          onValueChange={(value) => {
            const tab = RAIL.flatMap((entry) => entry.tabs).find((entry) => entry.id === value);
            if (tab) setActiveTab(tab.id);
          }}
          orientation="vertical"
          // The phone list is a menu of pages: arrows walk it, Enter opens a page.
          activationMode={isPhone ? "manual" : "automatic"}
          className="flex min-h-0 flex-1"
        >
          <div
            ref={railRef}
            className={cn(
              "flex min-h-0 w-full flex-col bg-[color:var(--aqt-bg-2)] md:w-60 md:shrink-0 md:border-r md:border-[color:var(--aqt-border)]",
              sectionOpen && "max-md:hidden"
            )}
          >
            {/* pr-14 keeps the title clear of the dialog's close button. */}
            <div className="flex min-h-14 shrink-0 items-center py-3 pl-4 pr-14 md:pl-5 md:pr-4">
              <DialogTitle>
                {t("title")}
              </DialogTitle>
            </div>
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-2 pb-4 md:px-3">
              {RAIL.map(({ group, tabs }) => (
                <div key={group}>
                  <p id={`account-settings-rail-${group}`} className={cn(eyebrowClass("faint"), "px-2.5 pb-1.5")}>
                    {t(`groups.${group}`)}
                  </p>
                  <TabsList variant="rail" aria-labelledby={`account-settings-rail-${group}`}>
                    {tabs.map(({ id, icon: Icon }) => (
                      // Also on the open tab: Radix reports no change for it, and on a
                      // phone that tap is what opens its page again.
                      <TabsTrigger key={id} value={id} onClick={() => setActiveTab(id)}>
                        <Icon aria-hidden />
                        <span className="min-w-0 flex-1 truncate text-left">{t(`tabs.${id}`)}</span>
                        <ChevronRight aria-hidden className="text-[color:var(--aqt-fg-dim)] md:hidden" />
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </div>
              ))}
            </div>
          </div>

          <div className={cn("flex min-h-0 min-w-0 flex-1 flex-col", !sectionOpen && "max-md:hidden")}>
            <header className="flex shrink-0 items-start gap-2 border-b border-[color:var(--aqt-border)] py-4 pl-3 pr-14 sm:pl-5 md:py-5 md:pl-8">
              <Button
                variant="ghost"
                size="icon-sm"
                className="mt-0.5 shrink-0 md:hidden"
                aria-label={t("back")}
                onClick={showSections}
              >
                <ArrowLeft aria-hidden />
              </Button>
              <div className="flex min-w-0 flex-1 flex-wrap items-start justify-between gap-x-4 gap-y-3">
                <div className="min-w-0 max-w-prose">
                  <h3
                    ref={headingRef}
                    tabIndex={-1}
                    className="font-display text-title font-semibold text-[color:var(--aqt-fg)] outline-hidden"
                  >
                    {t(`${activeTab}.title`)}
                  </h3>
                  <p className="mt-1 text-body text-pretty text-[color:var(--aqt-fg-muted)]">
                    {t(`${activeTab}.desc`)}
                  </p>
                </div>
                {activeTab === "profile" && profileHref ? (
                  <Button variant="outline" size="sm" asChild className="shrink-0">
                    <Link href={profileHref} onClick={close}>
                      {t("publicProfile")}
                      <ArrowUpRight aria-hidden />
                    </Link>
                  </Button>
                ) : null}
              </div>
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 sm:px-6 md:px-8 md:py-6">
              {RAIL.flatMap((entry) => entry.tabs).map(({ id }) => (
                <TabsContent key={id} value={id}>
                  {PANELS[id]}
                </TabsContent>
              ))}
            </div>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
};

export default AccountSettingsDialog;
