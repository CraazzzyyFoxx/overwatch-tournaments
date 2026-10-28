"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";

import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import { Label } from "@/components/ui/label";
import { GameMark } from "@/components/workspace/GameMark";
import type { DisciplineDescriptor } from "@/types/discipline.types";

/**
 * A creation form's "Game" field (spec §7.2): a combobox of the enabled games. The caller passes the
 * default (`defaultCreationGame`) and locks the field once the entity exists. Only a different game
 * is reported: picking the selected one again is no pick, so whatever the form keeps per game stays.
 */
export function GameField({
  games,
  value,
  onChange,
  disabled,
  id
}: Readonly<{
  games: DisciplineDescriptor[];
  value: string | null;
  onChange: (code: string) => void;
  disabled?: boolean;
  id?: string;
}>) {
  const t = useTranslations("common.discipline");
  const fallbackId = useId();
  const triggerId = id ?? fallbackId;
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const enabled = games.filter((game) => game.enabled);
  const selected = enabled.find((game) => game.code === value);

  const close = () => {
    setOpen(false);
    setSearch("");
  };

  return (
    <div className="space-y-1.5">
      <Label htmlFor={triggerId}>{t("field")}</Label>
      <Combobox
        id={triggerId}
        open={open}
        onOpenChange={(next) => (next ? setOpen(true) : close())}
        label={
          selected && (
            <span className="flex items-center gap-2">
              <GameMark discipline={selected} size={16} decorative />
              {selected.name}
            </span>
          )
        }
        placeholder={t("fieldPlaceholder")}
        labelTitle={selected?.name}
        disabled={disabled}
        searchValue={search}
        onSearchValueChange={setSearch}
        searchPlaceholder={t("fieldSearch")}
        emptyMessage={t("fieldEmpty")}
      >
        <CommandGroup>
          {enabled.map((game) => (
            <CommandItem
              key={game.code}
              value={`${game.name} ${game.code}`}
              onSelect={() => {
                if (game.code !== value) onChange(game.code);
                close();
              }}
            >
              <GameMark discipline={game} size={16} decorative />
              <span className="flex-1 truncate">{game.name}</span>
              <ComboboxCheck selected={game.code === value} />
            </CommandItem>
          ))}
        </CommandGroup>
      </Combobox>
    </div>
  );
}
