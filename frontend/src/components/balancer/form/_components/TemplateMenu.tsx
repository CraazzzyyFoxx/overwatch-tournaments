"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save, Upload } from "lucide-react";
import { useTranslations } from "next-intl";

import { EmptyNote } from "@/components/kit/EmptyNote";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fieldErrorsFrom } from "@/lib/forms/form-errors";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import registrationFormTemplatesService from "@/services/registration-form-templates.service";
import type { FormSchema } from "@/types/forms.types";
import { Spinner } from "@/components/ui/spinner";

export const registrationFormTemplatesKey = (workspaceId: number) =>
  ["admin", "registration-form-templates", workspaceId] as const;

/**
 * Workspace templates, from the tournament's builder.
 *
 * "Save as template" snapshots the form as the SERVER holds it
 * (`save_from_form`), so it is refused while the draft is dirty: silently
 * storing the last saved questionnaire under the name the organizer just typed
 * for the one on screen is the kind of near-miss nobody notices until the next
 * tournament opens with the wrong questions.
 *
 * "Load" only replaces the local draft. Nothing is written until the organizer
 * saves, which keeps the destructive step behind the same confirmation as
 * every other schema edit.
 */
export function TemplateMenu({
  workspaceId,
  tournamentId,
  dirty,
  onLoad
}: Readonly<{
  workspaceId: number | null;
  tournamentId: number;
  dirty: boolean;
  onLoad: (schema: FormSchema) => void;
}>) {
  const t = useTranslations("registrationFormAdmin.templates");
  const tErrors = useTranslations("forms.errors");
  const queryClient = useQueryClient();

  const [loadOpen, setLoadOpen] = useState(false);
  const [saveOpen, setSaveOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState("");

  const listQuery = useQuery({
    queryKey: registrationFormTemplatesKey(workspaceId ?? 0),
    queryFn: () => registrationFormTemplatesService.list(workspaceId as number),
    enabled: loadOpen && workspaceId !== null
  });

  const saveMutation = useMutation({
    mutationFn: () => registrationFormTemplatesService.saveFromForm(tournamentId, name.trim()),
    onSuccess: async () => {
      if (workspaceId !== null) {
        await queryClient.invalidateQueries({
          queryKey: registrationFormTemplatesKey(workspaceId)
        });
      }
      setSaveOpen(false);
      setName("");
      notify.success(t("savedToast"));
    },
    onError: (error) => notify.error(fieldErrorsFrom(error, tErrors).form ?? t("saveFailed"))
  });

  const templates = listQuery.data ?? [];
  const selected = templates.find((template) => template.id === selectedId) ?? null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            {t("menu")}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => {
              setSelectedId(null);
              setLoadOpen(true);
            }}
          >
            <Upload className="mr-2 size-3.5" aria-hidden />
            {t("load")}
          </DropdownMenuItem>
          <DropdownMenuItem disabled={dirty} onSelect={() => setSaveOpen(true)}>
            <Save className="mr-2 size-3.5" aria-hidden />
            {t("saveAs")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={loadOpen} onOpenChange={setLoadOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("loadTitle")}</DialogTitle>
            <DialogDescription>{t("loadDescription")}</DialogDescription>
          </DialogHeader>

          {listQuery.isLoading ? (
            <output className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
              <Spinner />
              {t("loading")}
            </output>
          ) : templates.length === 0 ? (
            <EmptyNote title={t("emptyTitle")}>{t("emptyHint")}</EmptyNote>
          ) : (
            <div className="grid max-h-72 gap-1.5 overflow-y-auto">
              {templates.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  aria-pressed={template.id === selectedId}
                  onClick={() => setSelectedId(template.id)}
                  className={cn(
                    "rounded-lg border px-3 py-2 text-left text-sm",
                    template.id === selectedId
                      ? "border-primary/40 bg-primary/10"
                      : "border-border/60 hover:border-border"
                  )}
                >
                  <span className="block font-medium">{template.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {t("sectionCount", { count: template.form_schema.sections.length })}
                  </span>
                </button>
              ))}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setLoadOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={selected === null}
              onClick={() => {
                if (!selected) return;
                onLoad(selected.form_schema);
                setLoadOpen(false);
                notify.success(t("loadedToast", { name: selected.name }));
              }}
            >
              {t("loadConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("saveAsTitle")}</DialogTitle>
            <DialogDescription>{t("saveAsDescription")}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor="registration-template-name">{t("nameLabel")}</Label>
            <Input
              id="registration-template-name"
              value={name}
              placeholder={t("namePlaceholder")}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={name.trim().length === 0 || saveMutation.isPending}
              onClick={() => saveMutation.mutate()}
            >
              {t("saveConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
