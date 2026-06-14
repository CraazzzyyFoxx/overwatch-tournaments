import React from "react";
import Image from "next/image";
import Link from "next/link";
import type { LucideIcon } from "lucide-react";
import { ArrowRight, Home, Radar, Swords, Trophy, Users } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { SITE_NAME } from "@/config/site";

const quickLinks: {
  href: string;
  title: string;
  description: string;
  icon: LucideIcon;
}[] = [
  {
    href: "/tournaments",
    title: "Tournaments",
    description: "Return to the full tournament board.",
    icon: Trophy
  },
  {
    href: "/users",
    title: "Players",
    description: "Jump into player profiles and rankings.",
    icon: Users
  },
  {
    href: "/encounters",
    title: "Encounters",
    description: "Open recent match breakdowns and results.",
    icon: Swords
  }
];

export default function NotFound() {
  return (
    <div className="flex flex-1 items-center py-4 md:py-8">
      <section
        className="liquid-glass relative isolate w-full overflow-hidden rounded-[32px] border border-border/60 px-6 py-8 sm:px-8 sm:py-10 lg:px-12 lg:py-12"
        style={
          {
            "--lg-a": "56 189 248",
            "--lg-b": "99 102 241",
            "--lg-c": "248 113 113"
          } as React.CSSProperties
        }
      >
        <div
          aria-hidden="true"
          className="absolute inset-0 bg-[linear-gradient(120deg,transparent_0%,rgba(255,255,255,0.04)_24%,transparent_48%,rgba(255,255,255,0.03)_72%,transparent_100%)]"
        />
        <div aria-hidden="true" className="absolute -left-16 top-12 h-56 w-56 rounded-full bg-sky-500/10 blur-3xl" />
        <div aria-hidden="true" className="absolute bottom-0 right-0 h-72 w-72 rounded-full bg-indigo-500/10 blur-3xl" />
        <div
          aria-hidden="true"
          className="absolute right-5 top-5 font-mono text-[4rem] font-black leading-none tracking-[-0.08em] text-foreground/5 sm:text-[5.5rem] lg:text-[7rem]"
        >
          404
        </div>

        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1fr),24rem] lg:items-start lg:gap-10 xl:grid-cols-[minmax(0,1fr),27rem]">
          <div className="max-w-2xl pt-2">
            <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/20 bg-sky-400/10 px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.32em] text-sky-200">
              <Radar className="size-4" aria-hidden="true" />
              404 // route unavailable
            </div>

            <h1 className="mt-6 max-w-xl text-4xl font-semibold tracking-[-0.04em] text-foreground sm:text-5xl lg:text-6xl">
              That route is off the board.
            </h1>

            <p className="mt-5 max-w-xl text-base leading-7 text-muted-foreground sm:text-lg">
              The page you requested is gone or never existed. Head back to {SITE_NAME} or jump
              into one of the live sections below.
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg" className="rounded-full px-6 shadow-lg shadow-sky-950/30">
                <Link href="/">
                  <Home className="size-4" aria-hidden="true" />
                  Back to dashboard
                </Link>
              </Button>

              <Button
                asChild
                size="lg"
                variant="outline"
                className="rounded-full border-border/70 bg-background/50 px-6 backdrop-blur-sm"
              >
                <Link href="/tournaments">
                  <Trophy className="size-4" aria-hidden="true" />
                  Browse tournaments
                </Link>
              </Button>
            </div>

          </div>

          <div className="space-y-4 lg:justify-self-end lg:w-full">
            <Card className="liquid-glass-panel relative overflow-hidden border-border/60 bg-card/75 p-3">
              <div className="relative aspect-[5/4] overflow-hidden rounded-[24px] border border-border/60 bg-black/20">
                <Image
                  src="/not-found.avif"
                  alt=""
                  fill
                  sizes="(min-width: 1280px) 27rem, (min-width: 1024px) 24rem, 100vw"
                  className="object-cover opacity-70"
                />
                <div
                  aria-hidden="true"
                  className="absolute inset-0 bg-[linear-gradient(180deg,rgba(2,6,23,0.18)_0%,rgba(2,6,23,0.36)_42%,rgba(2,6,23,0.88)_100%)]"
                />
                <div className="absolute inset-x-0 bottom-0 p-5 sm:p-6">
                  <p className="font-mono text-[11px] uppercase tracking-[0.32em] text-sky-100/75">
                    recovery map
                  </p>
                  <p className="mt-2 text-2xl font-semibold tracking-[-0.03em] text-white sm:text-3xl">
                    Jump back into the tournament feed.
                  </p>
                  <p className="mt-2 max-w-sm text-sm leading-6 text-slate-200/80">
                    The page may have moved, expired, or never existed. The live sections below are
                    safe entry points.
                  </p>
                </div>
                <div className="absolute left-5 top-5 rounded-full border border-white/15 bg-black/25 px-3 py-1 font-mono text-[11px] font-semibold uppercase tracking-[0.32em] text-white/80 backdrop-blur-sm">
                  404
                </div>
              </div>
            </Card>

            <Card className="liquid-glass-panel border-border/60 bg-card/75 p-4 sm:p-5">
              <div className="px-1">
                <p className="font-mono text-[11px] uppercase tracking-[0.32em] text-muted-foreground">
                  Quick recovery
                </p>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  Open one of the active sections below and continue browsing from a known route.
                </p>
              </div>

              <div className="mt-4 grid gap-3">
                {quickLinks.map((item) => {
                  const Icon = item.icon;

                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="group flex items-center gap-4 rounded-[22px] border border-border/60 bg-background/35 p-4 transition-colors duration-200 hover:bg-background/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      <div className="flex size-11 shrink-0 items-center justify-center rounded-2xl border border-border/60 bg-background/60 text-foreground">
                        <Icon className="size-4" aria-hidden="true" />
                      </div>

                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-semibold text-foreground">{item.title}</p>
                        <p className="mt-1 text-sm leading-6 text-muted-foreground">{item.description}</p>
                      </div>

                      <ArrowRight
                        className="size-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:translate-x-1"
                        aria-hidden="true"
                      />
                    </Link>
                  );
                })}
              </div>
            </Card>
          </div>
        </div>
      </section>
    </div>
  );
}
