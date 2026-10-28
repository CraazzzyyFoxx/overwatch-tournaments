"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { PlayerAvatar, type PlayerIdentity } from "@/components/PlayerAvatar";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { OverlayBar } from "@/components/ui/overlay-bar";

/** The compare tool takes exactly two players. */
const MAX_COMPARE = 2;

export interface CompareSelection {
  selected: PlayerIdentity[];
  isSelected: (id: number) => boolean;
  /** True once the picker is full — further rows render disabled, not inert-looking. */
  isFull: boolean;
  toggle: (user: PlayerIdentity) => void;
  clear: () => void;
}

/**
 * Compare picks are local state, not URL state: they are a transient staging
 * area for one navigation, and the compare page owns the shareable address.
 */
export function useCompareSelection(): CompareSelection {
  const [selected, setSelected] = useState<PlayerIdentity[]>([]);

  const toggle = useCallback((user: PlayerIdentity) => {
    setSelected((previous) => {
      if (previous.some((entry) => entry.id === user.id)) {
        return previous.filter((entry) => entry.id !== user.id);
      }
      if (previous.length >= MAX_COMPARE) return previous;
      return [...previous, user];
    });
  }, []);

  const clear = useCallback(() => setSelected([]), []);

  return {
    selected,
    isSelected: (id) => selected.some((entry) => entry.id === id),
    isFull: selected.length >= MAX_COMPARE,
    toggle,
    clear
  };
}

/** Bottom overlay listing the picks, with the link to the compare page. */
export function UsersCompareBar({ compare }: Readonly<{ compare: CompareSelection }>) {
  const t = useTranslations();
  if (compare.selected.length === 0) return null;

  const [first, second] = compare.selected;
  const ready = compare.selected.length === MAX_COMPARE;

  return (
    <OverlayBar tone={ready ? "accent" : "neutral"} ariaLabel={t("users.list.compare.barLabel")}>
      <div className="flex flex-wrap items-center gap-2">
        <Eyebrow>{t("users.list.compare.title")}</Eyebrow>
        {compare.selected.map((user) => (
          <span
            key={user.id}
            className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-2)] py-1 pl-1 pr-1.5 text-caption"
          >
            <PlayerAvatar user={user} size={22} />
            <span className="max-w-[12rem] truncate">{user.name}</span>
            <Button
              variant="ghost-destructive"
              size="icon-xs"
              onClick={() => compare.toggle(user)}
              aria-label={t("users.list.compare.remove", { name: user.name })}
            >
              <X aria-hidden />
            </Button>
          </span>
        ))}

        <div className="ml-auto flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={compare.clear}>
            {t("users.list.compare.clear")}
          </Button>
          {ready ? (
            <Button asChild size="sm">
              <HoverPrefetchLink href={`/users/compare?user_id=${first.id}&target_user_id=${second.id}`}>
                {t("users.list.compare.open")}
              </HoverPrefetchLink>
            </Button>
          ) : (
            <span className="text-caption text-[color:var(--aqt-fg-faint)]">
              {t("users.list.compare.needTwo")}
            </span>
          )}
        </div>
      </div>
    </OverlayBar>
  );
}
