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
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAccountSessions, useRevokeAccountSession } from "@/hooks/use-account-sessions";
import { getApiErrorMessage } from "@/lib/api-error";
import { notify } from "@/lib/notify";
import type { AccountSession, AccountSessionStatus } from "@/types/auth.types";

const STATUS_CLASS: Record<
  AccountSessionStatus,
  { dotClassName: string; textClassName: string }
> = {
  active: { dotClassName: "bg-emerald-400", textClassName: "text-emerald-200" },
  revoked: { dotClassName: "bg-amber-300", textClassName: "text-amber-100" },
  expired: { dotClassName: "bg-slate-400", textClassName: "text-slate-300" }
};

const STATUS_KEY: Record<AccountSessionStatus, "statusActive" | "statusRevoked" | "statusExpired"> = {
  active: "statusActive",
  revoked: "statusRevoked",
  expired: "statusExpired"
};

function formatTimestamp(value: string | null | undefined, locale: string): string | null {
  if (!value) return null;

  return new Date(value).toLocaleString(locale === "ru" ? "ru-RU" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

function detectBrowser(userAgent: string): string | null {
  if (/Edg\//i.test(userAgent)) return "Edge";
  if (/OPR\//i.test(userAgent)) return "Opera";
  if (/Chrome\//i.test(userAgent)) return "Chrome";
  if (/Firefox\//i.test(userAgent)) return "Firefox";
  if (/Safari\//i.test(userAgent) && !/Chrome\//i.test(userAgent)) return "Safari";
  return null;
}

function detectPlatform(userAgent: string): string | null {
  if (/iPhone|iPad|iPod/i.test(userAgent)) return "iOS";
  if (/Android/i.test(userAgent)) return "Android";
  if (/Windows/i.test(userAgent)) return "Windows";
  if (/Mac OS X|Macintosh/i.test(userAgent)) return "macOS";
  if (/Linux/i.test(userAgent)) return "Linux";
  return null;
}

function StatusText({ status }: { status: AccountSessionStatus }) {
  const t = useTranslations("accountSettings.sessions");
  const meta = STATUS_CLASS[status];

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${meta.textClassName}`}>
      <span className={`size-1.5 rounded-full ${meta.dotClassName}`} />
      {t(STATUS_KEY[status])}
    </span>
  );
}

function DetailCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-white/5 bg-black/10 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 truncate text-xs text-slate-300">{value}</p>
    </div>
  );
}

function SummaryCell({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/5 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-lg font-semibold text-white">{value}</p>
    </div>
  );
}

function SessionRow({
  session,
  isRevoking,
  onRevoke
}: {
  session: AccountSession;
  isRevoking: boolean;
  onRevoke: (sessionId: string) => void;
}) {
  const t = useTranslations("accountSettings.sessions");
  const locale = useLocale();
  const canRevoke = !session.is_current && session.status === "active";

  const ua = session.user_agent;
  const browser = ua ? detectBrowser(ua) : null;
  const platform = ua ? detectPlatform(ua) : null;
  const device = !ua
    ? t("unknownDevice")
    : browser && platform
      ? t("deviceOn", { browser, platform })
      : (browser ?? platform ?? (ua.length > 72 ? `${ua.slice(0, 72)}...` : ua));

  return (
    <li className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-200">
              <LaptopMinimal className="size-4" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-white">{device}</p>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <StatusText status={session.status} />
                {session.is_current ? (
                  <span className="inline-flex items-center gap-1 text-sky-200">
                    <Shield className="size-3.5" />
                    {t("currentSession")}
                  </span>
                ) : null}
                {session.ip_address ? (
                  <span className="inline-flex min-w-0 items-center gap-1">
                    <MapPin className="size-3.5 shrink-0" />
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
              <ShieldOff className="size-4" />
              {t("revoke")}
            </Button>
          ) : null}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <DetailCell label={t("signedIn")} value={formatTimestamp(session.login_at, locale) ?? t("unavailable")} />
          <DetailCell label={t("lastSeen")} value={formatTimestamp(session.last_seen_at, locale) ?? t("unavailable")} />
          <DetailCell label={t("expires")} value={formatTimestamp(session.expires_at, locale) ?? t("unavailable")} />
          <DetailCell
            label={session.status === "revoked" ? t("revokedLabel") : t("sessionLabel")}
            value={
              session.status === "revoked"
                ? (formatTimestamp(session.revoked_at, locale) ?? t("unavailable"))
                : session.session_id
            }
          />
        </div>

        {session.user_agent ? (
          <div className="flex items-start gap-2 text-xs text-slate-500">
            <Clock3 className="mt-0.5 size-3.5 shrink-0" />
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
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-24 rounded-lg bg-white/5" />
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
        <p className="flex items-center gap-2">
          <AlertCircle className="size-4" />
          {getApiErrorMessage(error, t("loadFailed"))}
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-3 border-red-500/50 hover:bg-red-500/20 hover:text-red-100"
          onClick={() => {
            void refetch();
          }}
        >
          <RefreshCw className="size-4" />
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
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            {t("currentSectionTitle")}
          </h4>
          <ul className="flex flex-col gap-2">
            <SessionRow session={currentSession} isRevoking={false} onRevoke={handleRevoke} />
          </ul>
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("otherActiveTitle")}
        </h4>
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
          <div className="rounded-lg border border-dashed border-white/10 px-4 py-5 text-sm text-slate-400">
            {t("noOtherActive")}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {t("historyTitle")}
        </h4>
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
          <div className="rounded-lg border border-dashed border-white/10 px-4 py-5 text-sm text-slate-400">
            {t("noHistory")}
          </div>
        )}
      </section>
    </div>
  );
}
