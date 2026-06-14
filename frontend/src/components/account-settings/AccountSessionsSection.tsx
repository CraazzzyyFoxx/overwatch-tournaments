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

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useAccountSessions, useRevokeAccountSession } from "@/hooks/use-account-sessions";
import { getApiErrorMessage } from "@/lib/api-error";
import { notify } from "@/lib/notify";
import type { AccountSession, AccountSessionStatus } from "@/types/auth.types";

const STATUS_META: Record<
  AccountSessionStatus,
  {
    dotClassName: string;
    label: string;
    textClassName: string;
  }
> = {
  active: {
    dotClassName: "bg-emerald-400",
    label: "Active",
    textClassName: "text-emerald-200"
  },
  revoked: {
    dotClassName: "bg-amber-300",
    label: "Revoked",
    textClassName: "text-amber-100"
  },
  expired: {
    dotClassName: "bg-slate-400",
    label: "Expired",
    textClassName: "text-slate-300"
  }
};

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "Unavailable";

  return new Date(value).toLocaleString("en-US", {
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

function formatDeviceLabel(userAgent: string | null | undefined): string {
  if (!userAgent) return "Unknown device";

  const browser = detectBrowser(userAgent);
  const platform = detectPlatform(userAgent);

  if (browser && platform) return `${browser} on ${platform}`;
  if (browser) return browser;
  if (platform) return platform;

  return userAgent.length > 72 ? `${userAgent.slice(0, 72)}...` : userAgent;
}

function StatusText({ status }: { status: AccountSessionStatus }) {
  const meta = STATUS_META[status];

  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${meta.textClassName}`}>
      <span className={`size-1.5 rounded-full ${meta.dotClassName}`} />
      {meta.label}
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
  const canRevoke = !session.is_current && session.status === "active";

  return (
    <li className="rounded-lg border border-white/10 bg-white/[0.03] p-3">
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/5 text-slate-200">
              <LaptopMinimal className="size-4" />
            </div>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-white">
                {formatDeviceLabel(session.user_agent)}
              </p>
              <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                <StatusText status={session.status} />
                {session.is_current ? (
                  <span className="inline-flex items-center gap-1 text-sky-200">
                    <Shield className="size-3.5" />
                    Current session
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
              Revoke
            </Button>
          ) : null}
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <DetailCell label="Signed in" value={formatTimestamp(session.login_at)} />
          <DetailCell label="Last seen" value={formatTimestamp(session.last_seen_at)} />
          <DetailCell label="Expires" value={formatTimestamp(session.expires_at)} />
          <DetailCell
            label={session.status === "revoked" ? "Revoked" : "Session"}
            value={
              session.status === "revoked"
                ? formatTimestamp(session.revoked_at)
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
        notify.success("Session revoked", {
          description: "The selected session was signed out."
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
          {getApiErrorMessage(error, "Failed to load sessions")}
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
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="grid gap-2 sm:grid-cols-3">
        <SummaryCell label="Current" value={currentSession ? 1 : 0} />
        <SummaryCell label="Other active" value={otherActiveSessions.length} />
        <SummaryCell label="History" value={sessionHistory.length} />
      </div>

      {currentSession ? (
        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Current Session
          </h4>
          <ul className="flex flex-col gap-2">
            <SessionRow session={currentSession} isRevoking={false} onRevoke={handleRevoke} />
          </ul>
        </section>
      ) : null}

      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Other Active Sessions
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
            No other active sessions.
          </div>
        )}
      </section>

      <section className="flex flex-col gap-2">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Session History
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
            No historical sessions yet.
          </div>
        )}
      </section>
    </div>
  );
}
