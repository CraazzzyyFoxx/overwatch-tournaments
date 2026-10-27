"use client";

import { Bell } from "lucide-react";
import dynamic from "next/dynamic";
import { useTranslations } from "next-intl";

import { useBellSignal } from "@/components/notifications/bell-signal";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { useNotifications } from "@/hooks/useNotifications";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useMediaQuery } from "@/hooks/useMediaQuery";

// The panel renders only once the bell is opened: its rows, actions and
// tooltips load with that first open, not with every page.
const NotificationPanel = dynamic(() => import("@/components/notifications/NotificationPanel"), {
  ssr: false,
  loading: () => (
    <div aria-busy="true" className="space-y-2 p-4">
      <Skeleton className="h-5 w-32" />
      <Skeleton className="h-16 w-full" />
    </div>
  )
});

/** Below this the panel is the whole screen rather than a popover. */
const PHONE_QUERY = "(max-width: 639px)";

/**
 * The inbox lives behind its own control in the header — not inside the account
 * menu, where a `role="menu"` could not legally hold a row made of a link, two
 * tool buttons and an inline action.
 *
 * Renders nothing for a signed-out visitor: the inbox is per account, and the
 * one notification an anonymous reader can receive (a platform announcement)
 * has its own card in the floating stack.
 */
export function NotificationBell() {
  const { user } = useAuthProfile();
  if (user?.id == null) return null;
  return <SignedInBell authUserId={user.id} />;
}

function SignedInBell({ authUserId }: Readonly<{ authUserId: number }>) {
  const t = useTranslations();
  const inbox = useNotifications(authUserId);
  // Shared: the floating stack's "Ещё N" opens this same panel.
  const open = useBellSignal((state) => state.open);
  const setOpen = useBellSignal((state) => state.setOpen);
  const isPhone = useMediaQuery(PHONE_QUERY);

  const unread = inbox.unreadCount ?? 0;
  const trigger = (
    <Button
      variant="outline"
      size="icon"
      aria-label={unread > 0 ? t("notifications.bellLabel", { count: unread }) : t("notifications.title")}
      className="relative shrink-0"
    >
      <Bell aria-hidden />
      {unread > 0 && (
        <span
          aria-hidden
          className="absolute -right-1.5 -top-[7px] inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-[color:var(--aqt-card)] bg-[color:var(--aqt-rose)] px-[5px] text-label font-bold leading-[14px] tabular-nums text-[color:var(--aqt-bg)]"
        >
          {unread > 99 ? "99+" : unread}
        </span>
      )}
    </Button>
  );

  if (isPhone) {
    return (
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>{trigger}</SheetTrigger>
        {/* Full screen, not a bottom drawer: a phone has no room for a panel
            that is also a popover, and the list is the whole task. */}
        <SheetContent
          side="bottom"
          closeButton={false}
          className="inset-0 flex h-dvh max-h-none w-auto flex-col gap-0 overflow-hidden rounded-none border-0 bg-[color:var(--aqt-card-2)] p-0"
        >
          <NotificationPanel inbox={inbox} isPhone onClose={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        collisionPadding={16}
        animate={false}
        className="flex max-h-[min(640px,calc(100dvh-96px))] w-[400px] max-w-[calc(100vw-2rem)] flex-col overflow-hidden p-0"
        // The panel focuses its heading on mount (the first open waits for
        // its chunk, so the heading is not there yet when the popover opens).
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <NotificationPanel inbox={inbox} isPhone={false} onClose={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
}
