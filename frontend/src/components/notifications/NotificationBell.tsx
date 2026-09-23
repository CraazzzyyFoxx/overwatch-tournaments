"use client";

import { Bell } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import NotificationList from "@/components/notifications/NotificationList";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useNotifications } from "@/hooks/useNotifications";

/** The authenticated inbox; Radix owns dismissal and focus restoration. */
const NotificationBell = () => {
  const t = useTranslations<never>();
  const { user } = useAuthProfile();
  const authUserId = user?.id ?? null;
  const [open, setOpen] = useState(false);
  const headingId = useId();
  const notifications = useNotifications(authUserId);
  const { unreadCount } = notifications;

  if (authUserId == null) return null;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          static={false}
          variant="ghost"
          size="icon"
          className="relative size-9 rounded-lg text-muted-foreground transition-colors hover:text-foreground data-[state=open]:bg-accent data-[state=open]:text-accent-foreground [&_svg]:size-5"
          aria-label={
            unreadCount == null
              ? t("notifications.title")
              : t("notifications.bell", { count: unreadCount })
          }
        >
          <Bell aria-hidden strokeWidth={1.75} />
          {unreadCount != null && unreadCount > 0 && (
            <span
              aria-hidden
              className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-label font-bold tabular-nums leading-none text-destructive-foreground ring-2 ring-background"
            >
              {unreadCount > 99 ? "99+" : unreadCount}
            </span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        collisionPadding={12}
        aria-labelledby={headingId}
        animate={false}
        // Land on the panel, not its first icon action: focusing that button
        // would pop its tooltip on every open. Tab still reaches it first.
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          (event.currentTarget as HTMLElement).focus();
        }}
        className="w-[380px] max-w-[calc(100vw-1.5rem)] p-0 motion-safe:data-[state=open]:animate-in motion-safe:data-[state=closed]:animate-out motion-safe:data-[state=open]:fade-in-0 motion-safe:data-[state=closed]:fade-out-0 motion-safe:duration-150 motion-safe:ease-out"
      >
        <NotificationList headingId={headingId} {...notifications} />
      </PopoverContent>
    </Popover>
  );
};

export default NotificationBell;
