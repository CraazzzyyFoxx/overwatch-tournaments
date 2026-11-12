"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import type { TournamentLinkKind } from "@/types/stream.types";
import { LINK_KINDS, type LinkForm } from "./model";

/** Body of the add/edit link dialog; `fieldErrors` comes from `linkFieldErrors`. */
export function LinkFormFields({
  formData,
  onChange,
  fieldErrors
}: Readonly<{
  formData: LinkForm;
  onChange: (next: LinkForm) => void;
  fieldErrors: Record<string, string>;
}>) {
  const t = useTranslations("adminTournament.links");
  const formId = useId();
  const kindFieldId = `${formId}-kind`;
  const labelFieldId = `${formId}-label`;
  const urlFieldId = `${formId}-url`;
  const sortFieldId = `${formId}-sort-order`;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor={kindFieldId}>{t("kind")}</Label>
        <Select
          value={formData.kind}
          onValueChange={(kind) =>
            onChange({ ...formData, kind: kind as TournamentLinkKind })
          }
        >
          <SelectTrigger
            id={kindFieldId}
            aria-invalid={fieldErrors.kind ? true : undefined}
            aria-describedby={fieldErrors.kind ? `${kindFieldId}-error` : undefined}
          >
            <SelectValue placeholder={t("pickKind")} />
          </SelectTrigger>
          <SelectContent>
            {LINK_KINDS.map((kind) => (
              <SelectItem key={kind.value} value={kind.value}>
                {t(`kinds.${kind.value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {fieldErrors.kind && (
          <p id={`${kindFieldId}-error`} className="text-xs text-destructive">
            {fieldErrors.kind}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {t("streamHint")}
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor={urlFieldId}>{t("url")}</Label>
        <Input
          id={urlFieldId}
          type="url"
          value={formData.url}
          onChange={(event) => onChange({ ...formData, url: event.target.value })}
          placeholder="https://twitch.tv/example"
          aria-invalid={fieldErrors.url ? true : undefined}
          aria-describedby={fieldErrors.url ? `${urlFieldId}-error` : undefined}
          required
        />
        {fieldErrors.url && (
          <p id={`${urlFieldId}-error`} className="text-xs text-destructive">
            {fieldErrors.url}
          </p>
        )}
      </div>

      <div className="space-y-2">
        <Label htmlFor={labelFieldId}>{t("label")}</Label>
        <Input
          id={labelFieldId}
          value={formData.label}
          onChange={(event) => onChange({ ...formData, label: event.target.value })}
          placeholder={t("mainBroadcast")}
          aria-invalid={fieldErrors.label ? true : undefined}
          aria-describedby={fieldErrors.label ? `${labelFieldId}-error` : undefined}
        />
        {fieldErrors.label && (
          <p id={`${labelFieldId}-error`} className="text-xs text-destructive">
            {fieldErrors.label}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {t("labelHint")}
        </p>
      </div>

      <div className="space-y-2">
        <Label htmlFor={sortFieldId}>{t("orderLabel")}</Label>
        <Input
          id={sortFieldId}
          type="number"
          inputMode="numeric"
          step={1}
          className="w-32"
          value={formData.sort_order}
          onChange={(event) =>
            onChange({ ...formData, sort_order: Number(event.target.value) || 0 })
          }
          aria-invalid={fieldErrors.sort_order ? true : undefined}
          aria-describedby={fieldErrors.sort_order ? `${sortFieldId}-error` : undefined}
        />
        {fieldErrors.sort_order && (
          <p id={`${sortFieldId}-error`} className="text-xs text-destructive">
            {fieldErrors.sort_order}
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          {t("orderHint")}
        </p>
      </div>
    </div>
  );
}
