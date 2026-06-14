"use client";

import Link from "next/link";
import { BarChart3, Shield, Swords, Trophy, UserCircle, Users, type LucideIcon } from "lucide-react";

import { CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SurfaceCard } from "./SurfaceCard";

export type QuickAccessItem = {
  href: string;
  title: string;
  icon: LucideIcon;
};

interface QuickAccessGridProps {
  items: QuickAccessItem[];
}

export function QuickAccessGrid({ items }: QuickAccessGridProps) {
  if (items.length === 0) return null;

  return (
    <SurfaceCard>
      <CardHeader className="p-5 pb-3">
        <CardTitle className="text-sm font-semibold">Quick Access</CardTitle>
        <CardDescription className="text-xs">Operational entry points</CardDescription>
      </CardHeader>
      <CardContent className="px-5 pb-5">
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.title}
                href={item.href}
                className="flex items-center gap-3 rounded-xl border border-border/50 bg-background/45 p-3 transition-colors hover:bg-accent/40"
              >
                <div className="flex size-8 items-center justify-center rounded-lg border border-border/50 bg-background/60 text-muted-foreground shrink-0">
                  <Icon className="size-4" />
                </div>
                <span className="text-sm font-medium text-foreground">{item.title}</span>
              </Link>
            );
          })}
        </div>
      </CardContent>
    </SurfaceCard>
  );
}
