"use client";

import { useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";

import { AdminCombobox, AdminComboboxCheck } from "@/components/admin/AdminCombobox";
import { Button } from "@/components/ui/button";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getApiErrorMessage } from "@/lib/api-error";
import type { CustomGame } from "@/services/custom-game.service";

type PickupCreateMixDialogProps = {
  games: CustomGame[];
  creating: boolean;
  onCreate: (name: string, cloneFromGameId: number | null) => Promise<unknown>;
  onClose: () => void;
};

/** Mounted only while open, so dismissal starts a fresh form; failed requests do not. */
export function PickupCreateMixDialog({
  games,
  creating,
  onCreate,
  onClose
}: Readonly<PickupCreateMixDialogProps>) {
  const t = useTranslations("mixes.create");
  const format = useFormatter();
  const [name, setName] = useState(() =>
    format.dateTime(new Date(), { day: "numeric", month: "long", year: "numeric" })
  );
  const [copyLineup, setCopyLineup] = useState(false);
  const [sourceId, setSourceId] = useState<number | null>(null);
  const [sourceOpen, setSourceOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [nameInvalid, setNameInvalid] = useState(false);
  const [sourceInvalid, setSourceInvalid] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const submitting = useRef(false);
  const source = games.find((game) => game.id === sourceId);
  const sourceLabel = (game: CustomGame) =>
    `${game.name} · ${game.host_display_name ?? `#${game.host_user_id}`}`;

  return (
    <DialogContent className="max-h-[calc(100dvh_-_2rem)] w-[calc(100%_-_2rem)] max-w-md overflow-y-auto overscroll-contain bg-card transition-[opacity,transform] [&>button]:size-8 [&>button]:grid [&>button]:place-items-center">
      <DialogHeader className="pe-6 text-start">
        <DialogTitle>{t("title")}</DialogTitle>
        <DialogDescription>{t("description")}</DialogDescription>
      </DialogHeader>
      <form
        noValidate
        className="min-w-0 space-y-6"
        onSubmit={async (event) => {
          event.preventDefault();
          if (submitting.current || creating) return;
          const invalidName = name.trim().length === 0;
          const invalidSource = copyLineup && !source;
          setNameInvalid(invalidName);
          setSourceInvalid(invalidSource);
          if (invalidName || invalidSource) {
            if (invalidName) nameRef.current?.focus();
            else document.getElementById("pickup-clone-from")?.focus();
            return;
          }
          submitting.current = true;
          setError(null);
          try {
            await onCreate(name.trim(), copyLineup ? sourceId : null);
            onClose();
          } catch (cause) {
            setError(getApiErrorMessage(cause, t("error")));
          } finally {
            submitting.current = false;
          }
        }}
      >
        <fieldset disabled={creating} className="min-w-0 space-y-5">
          <div className="space-y-2">
            <Label htmlFor="pickup-new-mix">{t("name")}</Label>
            <Input
              ref={nameRef}
              id="pickup-new-mix"
              name="name"
              required
              maxLength={255}
              autoComplete="off"
              value={name}
              placeholder={t("namePlaceholder")}
              onChange={(event) => {
                setName(event.target.value);
                setNameInvalid(false);
              }}
              aria-invalid={nameInvalid || undefined}
              aria-describedby={nameInvalid ? "pickup-name-error" : undefined}
            />
            {nameInvalid ? (
              <p id="pickup-name-error" className="text-caption text-destructive">
                {t("nameRequired")}
              </p>
            ) : null}
          </div>
          <fieldset className="min-w-0 space-y-2">
            <legend className="mb-2 text-body font-medium">{t("lineup")}</legend>
            <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border px-3 py-2 text-body has-checked:border-primary has-checked:bg-primary/5">
              <input
                type="radio"
                name="lineup"
                checked={!copyLineup}
                onChange={() => {
                  setCopyLineup(false);
                  setSourceInvalid(false);
                }}
                className="size-4 accent-primary"
              />
              {t("empty")}
            </label>
            {games.length > 0 ? (
              <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border px-3 py-2 text-body has-checked:border-primary has-checked:bg-primary/5">
                <input
                  type="radio"
                  name="lineup"
                  checked={copyLineup}
                  onChange={() => setCopyLineup(true)}
                  className="size-4 accent-primary"
                />
                {t("previous")}
              </label>
            ) : null}
          </fieldset>
          {copyLineup ? (
            <div className="min-w-0 space-y-2">
              <Label htmlFor="pickup-clone-from">{t("source")}</Label>
              <AdminCombobox
                id="pickup-clone-from"
                open={sourceOpen}
                onOpenChange={setSourceOpen}
                label={source ? sourceLabel(source) : t("source")}
                disabled={creating}
                aria-invalid={sourceInvalid || undefined}
                aria-describedby={sourceInvalid ? "pickup-source-error" : "pickup-lineup-hint"}
                triggerClassName="min-w-0"
                searchValue={search}
                onSearchValueChange={setSearch}
                searchPlaceholder={t("search")}
                emptyMessage={t("noResults")}
              >
                <CommandGroup>
                  {games.map((game) => (
                    <CommandItem
                      key={game.id}
                      value={`${sourceLabel(game)} ${game.id}`}
                      onSelect={() => {
                        setSourceId(game.id);
                        setSourceInvalid(false);
                        setSourceOpen(false);
                        setSearch("");
                      }}
                    >
                      <span className="min-w-0 flex-1 whitespace-normal [overflow-wrap:anywhere]">
                        {sourceLabel(game)}
                      </span>
                      <AdminComboboxCheck selected={sourceId === game.id} />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </AdminCombobox>
              {sourceInvalid ? (
                <p id="pickup-source-error" className="text-caption text-destructive">
                  {t("sourceRequired")}
                </p>
              ) : null}
            </div>
          ) : null}
          <p id="pickup-lineup-hint" className="text-caption text-muted-foreground">
            {t(copyLineup ? "copyHint" : "emptyHint")}
          </p>
        </fieldset>
        {error !== null ? (
          <div
            role="alert"
            className="space-y-2 rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-caption [overflow-wrap:anywhere]"
          >
            <p className="font-medium">{t("error")}</p>
            {error !== t("error") ? (
              <p className="whitespace-pre-wrap text-muted-foreground">{error}</p>
            ) : null}
          </div>
        ) : null}
        <p role="status" className="sr-only">
          {creating ? t("pending") : ""}
        </p>
        <DialogFooter className="gap-2">
          <Button type="button" variant="outline" disabled={creating} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button type="submit" disabled={creating}>
            {creating ? <Loader2 className="me-2 size-4 animate-spin" aria-hidden /> : null}
            {t("submit")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
