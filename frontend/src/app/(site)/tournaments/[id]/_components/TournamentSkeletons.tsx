"use client";

import React from "react";
import { useTranslations } from "next-intl";

import { PageHero } from "@/components/site/PageHero";
import { Skeleton } from "@/components/ui/skeleton";

const metaWidths = ["w-20", "w-28", "w-24"] as const;
const navWidths = ["w-24", "w-20", "w-28", "w-24", "w-20", "w-24"] as const;

export function TournamentShellSkeleton() {
  const t = useTranslations();

  return (
    <>
      <span className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {t("common.loading")}
      </span>
      <div className="aqt-tn space-y-4" aria-hidden="true">
        <PageHero
          eyebrow={<Skeleton className="h-3 w-56" />}
          title={
            <span
              aria-hidden
              className="block h-10 w-full max-w-lg animate-pulse rounded-md bg-primary/10 md:h-14"
            />
          }
          meta={
            <>
              {metaWidths.map((width) => (
                <Skeleton key={width} className={`h-7 rounded-full ${width}`} />
              ))}
            </>
          }
          lede={
            <span className="block space-y-2" aria-hidden>
              <span className="block h-3.5 w-full max-w-md animate-pulse rounded bg-primary/10" />
              <span className="block h-3.5 w-4/5 max-w-sm animate-pulse rounded bg-primary/10" />
            </span>
          }
          aside={
            <div className="grid grid-cols-2 gap-x-7 gap-y-5 xl:grid-cols-4">
              {Array.from({ length: 4 }, (_, index) => (
                <div key={index} className="flex flex-col gap-2">
                  <Skeleton className="h-2.5 w-16" />
                  <Skeleton className="h-8 w-12" />
                  <Skeleton className="h-2.5 w-14" />
                </div>
              ))}
            </div>
          }
        />

        <div className="tabs">
          {navWidths.map((width, index) => (
            <Skeleton key={`${width}-${index}`} className={`h-9 shrink-0 rounded-lg ${width}`} />
          ))}
        </div>

        <section className="min-w-0">
          <div className="rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] p-5 md:p-7">
            <div className="flex items-center justify-between gap-4">
              <Skeleton className="h-7 w-44" />
              <Skeleton className="h-9 w-28" />
            </div>
            <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 3 }, (_, index) => (
                <Skeleton key={index} className="h-36 w-full rounded-xl" />
              ))}
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
