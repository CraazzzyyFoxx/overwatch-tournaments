"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** A dashboard section's title: the display face, the same size framed or open. */
export const BLOCK_TITLE = "font-display text-heading font-semibold";

/**
 * One dashboard section that loads, fails and hides on its own. Framed: a
 * titled card around rows. Open (`framed={false}`): the heading over content
 * that frames itself (tiles), so a card never holds cards (DESIGN §5).
 */
export function Block({
  title,
  description,
  action,
  framed = true,
  className,
  contentClassName,
  children
}: Readonly<{
  title: string;
  description?: ReactNode;
  /** One control in the header (a toggle, a link). */
  action?: ReactNode;
  framed?: boolean;
  className?: string;
  /** Framed only: the rows' box, e.g. to scroll them under a fixed header. */
  contentClassName?: string;
  children?: ReactNode;
}>) {
  if (!framed) {
    return (
      <section aria-label={title} className={cn("flex flex-col gap-3", className)}>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 className={BLOCK_TITLE}>{title}</h2>
          {description ? <p className="text-body text-muted-foreground">{description}</p> : null}
          {action ? <div className="ml-auto">{action}</div> : null}
        </div>
        {children}
      </section>
    );
  }
  return (
    <Card asChild className={className}>
      <section aria-label={title}>
        <CardHeader>
          <div className="flex items-start justify-between gap-3">
            <h2 className={BLOCK_TITLE}>{title}</h2>
            {action}
          </div>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </CardHeader>
        {children ? <CardContent className={contentClassName}>{children}</CardContent> : null}
      </section>
    </Card>
  );
}

/** A failed read says so in place, never as a zero, and offers the retry. */
export function BlockError({ title, onRetry }: Readonly<{ title: string; onRetry: () => void }>) {
  const t = useTranslations("adminShell.dashboard");
  const tCommon = useTranslations("common");
  return (
    <Alert tone="danger">
      <AlertTriangle className="size-4" aria-hidden />
      <AlertTitle>{t("loadFailed", { block: title })}</AlertTitle>
      <AlertDescription>
        <Button variant="outline" size="sm" className="mt-2" onClick={onRetry}>
          {tCommon("retry")}
        </Button>
      </AlertDescription>
    </Alert>
  );
}
