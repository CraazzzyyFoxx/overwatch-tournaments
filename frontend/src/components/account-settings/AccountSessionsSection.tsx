"use client";

import { ChevronDown, HelpCircle, LogOut, Monitor, Smartphone } from "lucide-react";
import { useFormatter, useNow, useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAccountSessions, useRevokeAccountSession } from "@/hooks/use-account-sessions";
import { notify } from "@/lib/notify";
import { detectBrowser, detectPlatform } from "@/lib/user-agent";
import { cn } from "@/lib/utils";
import type { AccountSession } from "@/types/auth.types";
import { Spinner } from "@/components/ui/spinner";

import { SETTINGS_GROUP_HEADING_CLASS, SettingsGroup } from "./SettingsGroup";

const ROW_CLASS =
  "flex items-center gap-3 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] px-3 py-2.5";

type Meta = { text: string; title?: string };

/**
 * One session as a device row: what it is, where from, and the one timestamp
 * that answers "is this still me?". The raw user agent and the session id used
 * to be printed on every row (plus four boxed timestamps); neither helps a
 * person recognise a device, so the UA survives only as the name's tooltip.
 */
function SessionRow({
  session,
  now,
  pending,
  onRevoke
}: Readonly<{
  session: AccountSession;
  now: Date;
  pending: boolean;
  onRevoke?: (sessionId: string) => void;
}>) {
  const t = useTranslations("accountSettings.sessions");
  const format = useFormatter();

  const ua = session.user_agent ?? null;
  const browser = ua ? detectBrowser(ua) : null;
  const platform = ua ? detectPlatform(ua) : null;
  const device = !ua
    ? t("unknownDevice")
    : browser && platform
      ? t("deviceOn", { browser, platform })
      : (browser ?? platform ?? ua);
  const day = (value: string) => format.dateTime(new Date(value), { dateStyle: "medium" });
  const exact = (value: string) =>
    format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" });
  const DeviceIcon = !ua
    ? HelpCircle
    : platform === "iOS" || platform === "Android"
      ? Smartphone
      : Monitor;

  const ended = session.status !== "active";
  const meta: Meta[] = [];
  if (session.ip_address) meta.push({ text: session.ip_address });
  if (session.status === "revoked") {
    const at = session.revoked_at ?? session.last_seen_at;
    meta.push({ text: t("endedOn", { date: day(at) }), title: exact(at) });
  } else if (session.status === "expired") {
    meta.push({ text: t("expiredOn", { date: day(session.expires_at) }), title: exact(session.expires_at) });
  } else {
    if (!session.is_current) {
      meta.push({
        text: t("lastActive", { time: format.relativeTime(new Date(session.last_seen_at), now) }),
        title: exact(session.last_seen_at)
      });
    }
    meta.push({ text: t("signedInOn", { date: day(session.login_at) }), title: exact(session.login_at) });
  }

  return (
    <li className={ROW_CLASS}>
      <span
        aria-hidden
        className={cn(
          "flex size-9 shrink-0 items-center justify-center rounded-md bg-[color:var(--aqt-overlay-3)]",
          ended ? "text-[color:var(--aqt-fg-dim)]" : "text-[color:var(--aqt-fg-muted)]"
        )}
      >
        <DeviceIcon className="size-4" />
      </span>

      <div className="min-w-0 flex-1">
        {/* Wraps rather than truncating the name to fit the badge on phones. */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
          <p
            className={cn(
              "max-w-full truncate text-ui font-medium",
              ended ? "text-[color:var(--aqt-fg-muted)]" : "text-[color:var(--aqt-fg)]"
            )}
            title={ua ?? undefined}
          >
            {device}
          </p>
          {session.is_current ? (
            <Badge tone="accent" shape="pill" className="shrink-0">
              {t("thisDevice")}
            </Badge>
          ) : null}
        </div>
        <p className="break-words text-caption text-[color:var(--aqt-fg-dim)]">
          {meta.map((item, index) => (
            <span key={item.text}>
              {index > 0 ? <span aria-hidden> · </span> : null}
              <span title={item.title}>{item.text}</span>
            </span>
          ))}
        </p>
      </div>

      {onRevoke ? (
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          disabled={pending}
          aria-label={t("signOutAria", { device })}
          onClick={() => onRevoke(session.session_id)}
        >
          {pending ? <Spinner /> : <LogOut aria-hidden />}
          {/* Icon-only on phones; the aria-label still names the device. */}
          <span className="sr-only sm:not-sr-only">{t("signOut")}</span>
        </Button>
      ) : null}
    </li>
  );
}

export default function AccountSessionsSection() {
  const t = useTranslations("accountSettings.sessions");
  // Frozen at mount: the tab unmounts when closed, so "5 minutes ago" never
  // drifts far enough to matter and no row needs its own ticking clock.
  const now = useNow();
  const { data, isLoading, isError, refetch } = useAccountSessions();
  const revoke = useRevokeAccountSession();

  if (isLoading) {
    return (
      <div className="space-y-3" aria-hidden>
        <Skeleton className="h-5 w-40" />
        {["a", "b", "c"].map((key) => (
          <Skeleton key={key} className="h-15 rounded-lg" />
        ))}
      </div>
    );
  }

  if (isError) {
    return <PageStateCard state="error" title={t("loadFailed")} onAction={() => void refetch()} />;
  }

  const sessions = data ?? [];
  // Current first, then the other live sessions in the order the server sends.
  const active = sessions
    .filter((session) => session.status === "active")
    .sort((a, b) => Number(b.is_current) - Number(a.is_current));
  const hasOthers = active.some((session) => !session.is_current);
  const ended = sessions.filter((session) => session.status !== "active");

  // Revoke failures surface through the global MutationCache toast.
  const handleRevoke = (sessionId: string) => {
    revoke.mutate(sessionId, {
      onSuccess: () => notify.success(t("revokedToast"), { description: t("revokedToastDesc") })
    });
  };

  return (
    <div className="space-y-8">
      <SettingsGroup title={t("activeTitle")} description={t("activeDesc")}>
        <ul className="space-y-2">
          {active.map((session) => (
            <SessionRow
              key={session.session_id}
              session={session}
              now={now}
              pending={revoke.isPending && revoke.variables === session.session_id}
              onRevoke={session.is_current ? undefined : handleRevoke}
            />
          ))}
        </ul>
        {hasOthers ? null : (
          <p className="text-caption text-[color:var(--aqt-fg-dim)]">{t("noOtherActive")}</p>
        )}
      </SettingsGroup>

      {/* Ended sessions only matter when auditing, so they start collapsed. */}
      {ended.length > 0 ? (
        <details className="group space-y-3">
          <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
            <h4 className={SETTINGS_GROUP_HEADING_CLASS}>{t("historyTitle")}</h4>
            <span className="text-caption tabular-nums text-[color:var(--aqt-fg-dim)]">
              {ended.length}
            </span>
            <ChevronDown
              aria-hidden
              className="size-4 text-[color:var(--aqt-fg-muted)] transition-transform group-open:rotate-180"
            />
          </summary>
          <ul className="space-y-2">
            {ended.map((session) => (
              <SessionRow key={session.session_id} session={session} now={now} pending={false} />
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
