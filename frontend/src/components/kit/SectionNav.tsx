"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { cn } from "@/lib/utils";

export interface SectionNavItem {
  key: string;
  label: string;
  href: string;
  /** `danger` marks the destructive section (a Danger zone). */
  tone?: "danger";
  hidden?: boolean;
}

export interface SectionNavGroup {
  label?: string;
  items: SectionNavItem[];
}

export interface SectionNavProps {
  groups: SectionNavGroup[];
  activeKey: string;
}

/**
 * The section rail for every T5 settings screen.
 *
 * A settings hub has too many sections for a tab row (tournament settings has
 * eleven), so they become a vertical list of links. Below `md` there is no
 * room for a 200px rail beside a form, so the same list becomes a `Select` —
 * still one URL per section, so a link to "Danger zone" is shareable.
 */
export function SectionNav({ groups, activeKey }: Readonly<SectionNavProps>) {
  const router = useRouter();
  const visibleGroups = groups
    .map((group) => ({ ...group, items: group.items.filter((item) => !item.hidden) }))
    .filter((group) => group.items.length > 0);
  const allItems = visibleGroups.flatMap((group) => group.items);
  const active = allItems.find((item) => item.key === activeKey);

  return (
    <>
      <div className="md:hidden">
        <Select
          value={active?.key ?? ""}
          onValueChange={(key) => {
            const target = allItems.find((item) => item.key === key);
            if (target) router.push(target.href);
          }}
        >
          <SelectTrigger aria-label="Settings section">
            <SelectValue placeholder="Choose a section" />
          </SelectTrigger>
          <SelectContent>
            {visibleGroups.map((group) => (
              <SelectGroup key={group.label ?? "ungrouped"}>
                {group.label ? <SelectLabel>{group.label}</SelectLabel> : null}
                {group.items.map((item) => (
                  <SelectItem key={item.key} value={item.key}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectGroup>
            ))}
          </SelectContent>
        </Select>
      </div>

      <nav aria-label="Settings sections" className="hidden w-[200px] shrink-0 md:block">
        {visibleGroups.map((group) => (
          <div key={group.label ?? "ungrouped"} className="mb-4 last:mb-0">
            {group.label ? <p className={cn(EYEBROW_CLASS, "mb-1.5 px-2")}>{group.label}</p> : null}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const isActive = item.key === activeKey;
                return (
                  <li key={item.key}>
                    <Link
                      href={item.href}
                      aria-current={isActive ? "page" : undefined}
                      className={cn(
                        "block rounded-md px-2 py-1.5 text-sm transition-colors",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        isActive
                          ? "bg-accent/40 font-medium text-foreground"
                          : "text-muted-foreground hover:text-foreground",
                        item.tone === "danger" && !isActive && "text-danger/80 hover:text-danger"
                      )}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </>
  );
}
