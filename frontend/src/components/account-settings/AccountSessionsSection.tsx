"use client";

import {
  AlertCircle,
  Clock3,
  LaptopMinimal,
  MapPin,
  RefreshCw,
  Shield,
  ShieldOff
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAccountSessions, useRevokeAccountSession } from "@/hooks/use-account-sessions";
import { getApiErrorMessage } from "@/lib/api/error";
import { detectBrowser, detectPlatform } from "@/lib/user-agent";
import { notify } from "@/lib/notify";
import type { AccountSession, AccountSessionStatus } from "@/types/auth.types";

const STATUS_CLASS: Record<
  AccountSessionStatus,
  { dotClassName: string; textClassName: string }
> = {
  active: {
    dotClassName: "bg-[color:var(--aqt-emerald)]",
    textClassName: "text-[color:var(--aqt-emerald)]"
  },
  revoked: {
    dotClassName: "bg-[color:var(--aqt-amber)]",
    textClassName: "text-[color:var(--aqt-amber)]"
  },
  expired: {
    dotClassName: "bg-[color:var(--aqt-fg-faint)]",
    textClassName: "text-[color:var(--aqt-fg-dim)]"
  }
};

const STATUS_KEY: Record<AccountSessionStatus, "statusActive" | "statusRevoked" | "statusExpired"> = {
  active: "statusActive",
  revoked: "statusRevoked",
  expired: "statusExpired"
};

const SECTION_TITLE_CLASS =
  "text-xs font-semibold uppercase tracking-wide text-[color:var(--aqt-fg-dim)]";
const EMPTY_CLASS =
  "rounded-lg border border-dashed border-[color:var(--aqt-border-2)] px-4 py-5 text-sm text-[color:var(--aqt-fg-muted)]";

function StatusText({ status }: Readonly<{ status: AccountSessionStatus }>) {
  const t = useTranslations("accountSettings.sessions");
  const meta = STATUS_CLASS[status];

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${meta.textClassName}`}>
      <span aria-hidden className={`size-1.5 rounded-full ${meta.dotClassName}`} />
      {t(STATUS_KEY[status])}
    </span>
  );
}

function DetailCell({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="min-w-0 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)] px-3 py-2">
      <p className="text-label font-medium uppercase tracking-wide text-[color:var(--aqt-fg-dim)]">
        {label}
      </p>
      <p className="mt-0.5 truncate text-xs text-[color:var(--aqt-fg-muted)]">{value}</p>
    </div>
  );
}

function SummaryCell({ label, value }: Readonly<{ label: string; value: number }>) {
  return (
    <div className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] px-3 py-2">
      <p className="text-label font-medium uppercase tracking-wide text-[color:var(--aqt-fg-dim)]">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold tabular-nums text-[color:var(--aqt-fg)]">{value}</p>
    </div>
  );
}

function SessionRow({
  session,
  isRevoking,
  onRevoke
}: Readonly<{
  session: AccountSession;
  isRevoking: boolean;
  onRevoke: (sessionId: string) => void;
}>) {
  const t = useTranslations("accountSettings.sessions");
  // next-intl's formatter already carries the active locale, so the timestamps
  // follow it. This file used to hand-map `locale === "ru" ? "ru-RU" : "en-US"`.
  const format = useFormatter();
  const canRevoke = !session.is_current && session.status === "active";

  const formatTimestamp = (value: string | null | undefined): string =>
    value
      ? format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" })
      : t("unavailable");

  const ua = session.user_agent;
  const browser = ua ? detectBrowser(ua) : null;
  const platform = ua ? detectPlatform(ua) : null;
  const device = !ua
    ? t("unknownDevice")
    : browser && platform
      ? t("deviceOn", { browser, platform })
      : (browser ?? platform ?? (ua.length > 72 ? `${ua.slice(0, 72)}...` : ua));

  return (
    <li className="rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-2)] p-3">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-3)] text-[color:var(--aqt-fg-muted)]">
              <LaptopMinimal className="size-4" aria-hidden />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-[color:var(--aqt-fg)]">{device}</p>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[color:var(--aqt-fg-muted)]">
                <StatusText status={session.status} />
                {session.is_current ? (
                  <span className="inline-flex items-center gap-1 text-[color:var(--aqt-blue)]">
                    <Shield className="size-3.5" aria-hidden />
                    {t("currentSession")}
                  </span>
                ) : null}
                {session.ip_address ? (
                  <span className="inline-flex min-w-0 items-center gap-1">
                    <MapPin className="size-3.5 shrink-0" aria-hidden />
                    <span className="truncate">{session.ip_address}</span>
                  </span>
                ) : null}
              </div>
            </div>
          </div>

          {canRevoke ? (
            <Button
              variant="outline"
              size="sm"
              disabled={isRevoking}
              onClick={() => onRevoke(session.session_id)}
            >
              <ShieldOff className="size-4" aria-hidden />
              {t("revoke")}
            </Button>
          ) : null}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <DetailCell label={t("signedIn")} value={formatTimestamp(session.login_at)} />
          <DetailCell label={t("lastSeen")} value={formatTimestamp(session.last_seen_at)} />
          <DetailCell label={t("expires")} value={formatTimestamp(session.expires_at)} />
          <DetailCell
            label={session.status === "revoked" ? t("revokedLabel") : t("sessionLabel")}
            value={
              session.status === "revoked"
                ? formatTimestamp(session.revoked_at)
                : session.session_id
            }
          />
        </div>

        {session.user_agent ? (
          <div className="flex items-start gap-2 text-xs text-[color:var(--aqt-fg-dim)]">
            <Clock3 className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span className="break-all">{session.user_agent}</span>
          </div>
        ) : null}
      </div>
    </li>
  );
}

export default function AccountSessionsSection() {
  const t = useTranslations("accountSettings.sessions");
  const { data, isLoading, isError, error, refetch } = useAccountSessions();
  const revokeSessionMutation = useRevokeAccountSession();

  const sessions = data ?? [];
  const currentSession = sessions.find((session) => session.is_current) ?? null;
  const otherActiveSessions = sessions.filter(
    (session) => !session.is_current && session.status === "active"
  );
  const sessionHistory = sessions.filter(
    (session) => !session.is_current && session.status !== "active"
  );

  const handleRevoke = (sessionId: string) => {
    revokeSessionMutation.mutate(sessionId, {
      onSuccess: () => {
        notify.success(t("revokedToast"), {
          description: t("revokedToastDesc")
        });
      }
    });
  };

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        {["a", "b", "c"].map((key) => (
          <Skeleton key={key} className="h-24 rounded-lg" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div
        role="alert"
        className="rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive"
      >
        <p className="flex items-center gap-2">
          <AlertCircle className="size-4" aria-hidden />
          {getApiErrorMessage(error, t("loadFailed"))}
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3 border-destructive/50 hover:bg-destructive/20"
          onClick={() => {
            void refetch();
          }}
        >
          <RefreshCw className="size-4" aria-hidden />
          {t("retry")}
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-2 sm:grid-cols-3">
        <SummaryCell label={t("summaryCurrent")} value={currentSession ? 1 : 0} />
        <SummaryCell label={t("summaryOtherActive")} value={otherActiveSessions.length} />
        <SummaryCell label={t("summaryHistory")} value={sessionHistory.length} />
      </div>

      {currentSession ? (
        <section className="flex flex-col gap-2">
          <h4 className={SECTION_TITLE_CLASS}>{t("currentSectionTitle")}</h4>
          <ul className="flex flex-col gap-2">
            <SessionRow session={currentSession} isRevoking={false} onRevoke={handleRevoke} />
          </ul>
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <h4 className={SECTION_TITLE_CLASS}>{t("otherActiveTitle")}</h4>
        {otherActiveSessions.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {otherActiveSessions.map((session) => (
              <SessionRow
                key={session.session_id}
                session={session}
                isRevoking={
                  revokeSessionMutation.isPending &&
                  revokeSessionMutation.variables === session.session_id
                }
                onRevoke={handleRevoke}
              />
            ))}
          </ul>
        ) : (
          <div className={EMPTY_CLASS}>{t("noOtherActive")}</div>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h4 className={SECTION_TITLE_CLASS}>{t("historyTitle")}</h4>
        {sessionHistory.length > 0 ? (
          <ul className="flex flex-col gap-2">
            {sessionHistory.map((session) => (
              <SessionRow
                key={session.session_id}
                session={session}
                isRevoking={false}
                onRevoke={handleRevoke}
              />
            ))}
          </ul>
        ) : (
          <div className={EMPTY_CLASS}>{t("noHistory")}</div>
        )}
      </section>
    </div>
  );
}
