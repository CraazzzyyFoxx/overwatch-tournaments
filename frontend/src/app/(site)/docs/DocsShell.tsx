"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useMemo, useState, type ReactNode } from "react";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SearchField } from "@/components/ui/search-field";
import { cn } from "@/lib/utils";

import type { DocLink, DocSection } from "./nav";

const itemClass = cn(
  "block rounded-md px-2 py-1.5 text-sm transition-colors",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
);
const activeClass = "bg-accent/40 font-medium text-foreground";
const idleClass = "text-muted-foreground hover:text-foreground";

function matches(item: DocLink, q: string) {
  return item.title.toLowerCase().includes(q) || item.keywords.toLowerCase().includes(q);
}

export function DocsShell({
  sections,
  children,
}: Readonly<{ sections: DocSection[]; children: ReactNode }>) {
  const t = useTranslations("docs");
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();

  const current = sections.find(
    (section) => pathname === section.href || pathname.startsWith(`${section.href}/`),
  );

  // Search spans every audience: "check-in" is a player task and an organizer
  // setting, and the reader may not know which side their question is on.
  const groups = useMemo(() => {
    if (!q) return current?.groups ?? [];
    return sections
      .flatMap((section) =>
        section.groups.map((group) => ({
          label: `${section.label} · ${group.label}`,
          items: group.items.filter((item) => matches(item, q)),
        })),
      )
      .filter((group) => group.items.length > 0);
  }, [q, current, sections]);

  const activeHref = groups.flatMap((g) => g.items).find((item) => item.href === pathname)?.href;

  return (
    <div className="flex flex-col gap-6 pb-16 md:flex-row md:gap-10">
      <aside className="md:w-[220px] md:shrink-0">
        <nav aria-label={t("nav.audience")} className="mb-4 flex flex-wrap gap-1 md:flex-col">
          {sections.map((section) => {
            const active = current?.id === section.id;
            return (
              <Link
                key={section.id}
                href={section.href}
                aria-current={active ? "true" : undefined}
                className={cn(itemClass, active ? activeClass : idleClass)}
              >
                {section.label}
              </Link>
            );
          })}
        </nav>
        <SearchField
          value={query}
          onValueChange={setQuery}
          label={t("search.label")}
          placeholder={t("search.placeholder")}
          containerClassName="mb-4"
        />
        {groups.length > 0 ? (
          <div className="md:hidden">
            <Select value={activeHref ?? ""} onValueChange={(href) => router.push(href)}>
              <SelectTrigger aria-label={t("nav.select")}>
                <SelectValue placeholder={t("nav.select")} />
              </SelectTrigger>
              <SelectContent>
                {groups.map((group) => (
                  <SelectGroup key={group.label}>
                    <SelectLabel>{group.label}</SelectLabel>
                    {group.items.map((item) => (
                      <SelectItem key={item.href} value={item.href}>
                        {item.title}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                ))}
              </SelectContent>
            </Select>
          </div>
        ) : null}
        <nav aria-label={t("nav.label")} className="hidden md:block">
          {q && groups.length === 0 ? (
            <p className="px-2 text-sm text-muted-foreground">{t("search.empty", { query })}</p>
          ) : (
            groups.map((group) => (
              <div key={group.label} className="mb-4 last:mb-0">
                <p className="mb-1.5 px-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  {group.label}
                </p>
                <ul className="space-y-0.5">
                  {group.items.map((item) => {
                    const active = !item.bypassNext && item.href === pathname;
                    const className = cn(itemClass, active ? activeClass : idleClass);
                    return (
                      <li key={item.href}>
                        {item.bypassNext ? (
                          <a className={className} href={item.href}>
                            {item.title}
                          </a>
                        ) : (
                          <Link
                            className={className}
                            href={item.href}
                            aria-current={active ? "page" : undefined}
                          >
                            {item.title}
                          </Link>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))
          )}
        </nav>
      </aside>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
