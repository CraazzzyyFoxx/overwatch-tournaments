"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";

import { Combobox, ComboboxCheck } from "@/components/ui/combobox";
import { Button } from "@/components/ui/button";
import { CommandGroup, CommandItem } from "@/components/ui/command";
import {
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Field, FieldLabel, FieldTitle } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { getApiErrorMessage } from "@/lib/api/error";
import type { CustomGame } from "@/services/custom-game.service";
import { Spinner } from "@/components/ui/spinner";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Workspace } from "@/types/workspace.types";

type PickupCreateMixDialogProps = {
  games: CustomGame[];
  workspaces: Pick<Workspace, "id" | "name" | "disciplines_enabled">[];
  /** The installed games, for their names. */
  disciplines: readonly Pick<DisciplineDescriptor, "code" | "name">[];
  /**
   * The game the directory is showing: the mix is for it and no choice is offered. `null` under all games, where the
   * host names the game -- a mix is never created for an implied one.
   */
  fixedDiscipline: string | null;
  scopedWorkspaceId: number | null;
  creating: boolean;
  onCreate: (
    name: string,
    cloneFromGameId: number | null,
    workspaceId: number,
    discipline: string
  ) => Promise<unknown>;
  onClose: () => void;
};

/** Mounted only while open, so dismissal starts a fresh form; failed requests do not. */
export function PickupCreateMixDialog({
  games,
  workspaces,
  disciplines,
  fixedDiscipline,
  scopedWorkspaceId,
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
  const [pickedWorkspaceId, setPickedWorkspaceId] = useState<number | null>(null);
  const [workspaceInvalid, setWorkspaceInvalid] = useState(false);
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [workspaceSearch, setWorkspaceSearch] = useState("");
  const [pickedDiscipline, setPickedDiscipline] = useState<string | null>(null);
  const [disciplineInvalid, setDisciplineInvalid] = useState(false);
  const [disciplineOpen, setDisciplineOpen] = useState(false);
  const [disciplineSearch, setDisciplineSearch] = useState("");
  const workspaceId = scopedWorkspaceId ?? pickedWorkspaceId;
  const workspace = workspaces.find((item) => item.id === workspaceId);
  // The games this community runs; a directory's fixed game is the only choice there is.
  const enabledHere = disciplines.filter((item) => workspace?.disciplines_enabled.includes(item.code));
  const fixed = fixedDiscipline === null ? null : (disciplines.find((item) => item.code === fixedDiscipline) ?? null);
  const discipline =
    fixedDiscipline !== null
      ? (workspace?.disciplines_enabled.includes(fixedDiscipline) ? fixedDiscipline : null)
      : pickedDiscipline !== null && enabledHere.some((item) => item.code === pickedDiscipline)
        ? pickedDiscipline
        : enabledHere.length === 1
          ? enabledHere[0].code
          : null;
  // A copy starts from a mix of the same community AND game: it keeps its source's game.
  const sourceGames = games.filter((game) => game.workspace_id === workspaceId && game.discipline === discipline);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  const submitting = useRef(false);
  const source = sourceGames.find((game) => game.id === sourceId);
  const sourceLabel = (game: CustomGame) =>
    `${game.name} · ${game.host_display_name ?? `#${game.host_user_id}`}`;
  // A new community or game invalidates the copy source picked for the old one.
  const resetSource = () => {
    setSourceId(null);
    setCopyLineup(false);
    setSourceInvalid(false);
    setSearch("");
  };

  return (
    <DialogContent className="max-w-md">
      <DialogHeader>
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
          const invalidWorkspace = !workspace;
          const invalidDiscipline = discipline === null;
          setWorkspaceInvalid(invalidWorkspace);
          setNameInvalid(invalidName);
          setSourceInvalid(invalidSource);
          setDisciplineInvalid(invalidDiscipline && !invalidWorkspace);
          if (invalidName || invalidWorkspace || invalidDiscipline || invalidSource) {
            if (invalidWorkspace) document.getElementById("pickup-workspace")?.focus();
            else if (invalidDiscipline) document.getElementById("pickup-discipline")?.focus();
            else if (invalidName) nameRef.current?.focus();
            else document.getElementById("pickup-clone-from")?.focus();
            return;
          }
          submitting.current = true;
          setError(null);
          try {
            await onCreate(name.trim(), copyLineup ? sourceId : null, workspace!.id, discipline!);
            onClose();
          } catch (cause) {
            setError(getApiErrorMessage(cause, t("error")));
          } finally {
            submitting.current = false;
          }
        }}
      >
        <fieldset disabled={creating} className="min-w-0 space-y-5">
          {scopedWorkspaceId == null ? (
            <div className="space-y-2">
              <Label htmlFor="pickup-workspace">{t("workspace")}</Label>
              <Combobox
                id="pickup-workspace"
                open={workspaceOpen}
                onOpenChange={setWorkspaceOpen}
                label={workspace?.name}
                placeholder={t("workspacePlaceholder")}
                disabled={creating}
                aria-invalid={workspaceInvalid || undefined}
                aria-describedby={workspaceInvalid ? "pickup-workspace-error" : undefined}
                triggerClassName="min-w-0"
                searchValue={workspaceSearch}
                onSearchValueChange={setWorkspaceSearch}
                searchPlaceholder={t("searchWorkspace")}
                emptyMessage={t("noWorkspaces")}
              >
                <CommandGroup>
                  {workspaces.map((item) => (
                    <CommandItem
                      key={item.id}
                      value={`${item.name} ${item.id}`}
                      onSelect={() => {
                        setPickedWorkspaceId(item.id);
                        setWorkspaceInvalid(false);
                        setDisciplineInvalid(false);
                        setWorkspaceOpen(false);
                        setWorkspaceSearch("");
                        if (item.id !== pickedWorkspaceId) resetSource();
                      }}
                    >
                      <span className="min-w-0 flex-1 truncate">{item.name}</span>
                      <ComboboxCheck selected={pickedWorkspaceId === item.id} />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </Combobox>
              {workspaceInvalid ? <p id="pickup-workspace-error" className="text-caption text-destructive">{t("workspaceRequired")}</p> : null}
            </div>
          ) : null}
          {workspace === undefined ? null : fixedDiscipline !== null ? (
            <div className="space-y-1">
              <p className="text-body font-medium">{t("game")}</p>
              <p id="pickup-discipline" tabIndex={-1} className="text-body" aria-invalid={disciplineInvalid || undefined}>
                {fixed?.name ?? fixedDiscipline}
              </p>
              {discipline === null ? (
                <p role="alert" className="text-caption text-destructive">{t("gameUnavailable")}</p>
              ) : null}
            </div>
          ) : enabledHere.length > 1 ? (
            <div className="space-y-2">
              <Label htmlFor="pickup-discipline">{t("game")}</Label>
              <Combobox
                id="pickup-discipline"
                open={disciplineOpen}
                onOpenChange={setDisciplineOpen}
                label={enabledHere.find((item) => item.code === discipline)?.name}
                placeholder={t("gamePlaceholder")}
                disabled={creating}
                aria-invalid={disciplineInvalid || undefined}
                aria-describedby={disciplineInvalid ? "pickup-discipline-error" : undefined}
                triggerClassName="min-w-0"
                searchValue={disciplineSearch}
                onSearchValueChange={setDisciplineSearch}
                searchPlaceholder={t("searchGame")}
                emptyMessage={t("noGames")}
              >
                <CommandGroup>
                  {enabledHere.map((item) => (
                    <CommandItem
                      key={item.code}
                      value={`${item.name} ${item.code}`}
                      onSelect={() => {
                        setPickedDiscipline(item.code);
                        setDisciplineInvalid(false);
                        setDisciplineOpen(false);
                        setDisciplineSearch("");
                        if (item.code !== discipline) resetSource();
                      }}
                    >
                      <span className="min-w-0 flex-1 truncate">{item.name}</span>
                      <ComboboxCheck selected={discipline === item.code} />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </Combobox>
              {disciplineInvalid ? <p id="pickup-discipline-error" className="text-caption text-destructive">{t("gameRequired")}</p> : null}
            </div>
          ) : discipline !== null ? (
            <div className="space-y-1">
              <p className="text-body font-medium">{t("game")}</p>
              <p id="pickup-discipline" tabIndex={-1} className="text-body">{enabledHere[0].name}</p>
            </div>
          ) : (
            <p id="pickup-discipline" role="alert" tabIndex={-1} className="text-caption text-destructive">
              {t("gameUnavailable")}
            </p>
          )}
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
          <div className="min-w-0 space-y-2">
            <p id="pickup-lineup-label" className="text-body font-medium">{t("lineup")}</p>
            <RadioGroup
              aria-labelledby="pickup-lineup-label"
              value={copyLineup ? "previous" : "empty"}
              onValueChange={(value) => {
                setCopyLineup(value === "previous");
                if (value === "empty") setSourceInvalid(false);
              }}
              className="gap-2"
            >
              <FieldLabel htmlFor="pickup-lineup-empty">
                <Field orientation="horizontal">
                  <RadioGroupItem id="pickup-lineup-empty" value="empty" />
                  <FieldTitle>{t("empty")}</FieldTitle>
                </Field>
              </FieldLabel>
              {sourceGames.length > 0 ? (
                <FieldLabel htmlFor="pickup-lineup-previous">
                  <Field orientation="horizontal">
                    <RadioGroupItem id="pickup-lineup-previous" value="previous" />
                    <FieldTitle>{t("previous")}</FieldTitle>
                  </Field>
                </FieldLabel>
              ) : null}
            </RadioGroup>
          </div>
          {copyLineup ? (
            <div className="min-w-0 space-y-2">
              <Label htmlFor="pickup-clone-from">{t("source")}</Label>
              <Combobox
                id="pickup-clone-from"
                open={sourceOpen}
                onOpenChange={setSourceOpen}
                label={source && sourceLabel(source)}
                placeholder={t("source")}
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
                  {sourceGames.map((game) => (
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
                      <ComboboxCheck selected={sourceId === game.id} />
                    </CommandItem>
                  ))}
                </CommandGroup>
              </Combobox>
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
        <DialogFooter>
          <Button type="button" variant="outline" disabled={creating} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button type="submit" disabled={creating}>
            {creating ? <Spinner className="me-2" /> : null}
            {t("submit")}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  );
}
