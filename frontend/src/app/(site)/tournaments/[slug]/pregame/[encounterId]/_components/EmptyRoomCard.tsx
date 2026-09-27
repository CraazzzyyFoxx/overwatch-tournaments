"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowLeft, Clock, ShieldAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import type { PickBanUnavailableIcon } from "@/components/pick-ban/pick-ban-model";

/** One icon per cause, keyed by what `PICK_BAN_UNAVAILABLE_COPY` names. */
export const UNAVAILABLE_ICON: Record<PickBanUnavailableIcon, React.ReactNode> = {
  teams: <ShieldAlert className="h-6 w-6 text-[color:var(--aqt-teal)]" aria-hidden />,
  unconfigured: <ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />,
  misconfigured: <ShieldAlert className="h-6 w-6 text-[color:var(--aqt-amber)]" aria-hidden />,
  preview: <Clock className="h-6 w-6 text-[color:var(--aqt-fg-muted)]" aria-hidden />
};

/** The room with nothing to show: why it is empty, and the way back out. */
export function EmptyRoomCard({
  icon,
  title,
  hint,
  action,
  returnTo
}: Readonly<{
  icon: React.ReactNode;
  title: string;
  hint?: string;
  action?: React.ReactNode;
  returnTo: string;
}>) {
  const t = useTranslations("pickBan.room");

  return (
    <Card>
      <CardContent className="flex min-h-[40svh] flex-col items-center justify-center gap-3 p-8 text-center">
        {icon}
        <h1 className="font-onest text-xl font-semibold">{title}</h1>
        {hint ? (
          <p className="max-w-lg text-sm leading-relaxed text-[color:var(--aqt-fg-muted)]">
            {hint}
          </p>
        ) : null}
        <div className="mt-2 flex items-center gap-2">
          {action}
          <Button variant="outline" asChild>
            <Link href={returnTo}>
              <ArrowLeft className="mr-2 h-4 w-4" aria-hidden />
              {t("back")}
            </Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
