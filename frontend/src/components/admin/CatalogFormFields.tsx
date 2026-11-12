"use client";

/**
 * Shared "Name", "Image" and "Aliases" dialog fields for the game-catalogue admin
 * pages (maps, heroes, gamemodes). Every catalogue entity renders them the
 * same way, so they live here instead of being copy-pasted three times.
 */

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useMutation } from "@tanstack/react-query";

import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatAliasesInput, parseAliasesInput } from "@/lib/catalog-aliases";
import { notify } from "@/lib/notify";
import { MAX_CATALOG_IMAGE_BYTES } from "@/lib/uploads";
import adminService from "@/services/admin.service";
import type { CatalogKind } from "@/types/catalog.types";

interface CatalogNameFieldProps {
  id: string;
  value: string | undefined;
  onChange: (value: string) => void;
}

export function CatalogNameField({ id, value, onChange }: Readonly<CatalogNameFieldProps>) {
  const t = useTranslations("adminWorkspace.content.fields");
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("name")}</Label>
      <Input id={id} value={value} onChange={(e) => onChange(e.target.value)} required />
    </div>
  );
}

interface CatalogImageFieldProps {
  discipline: string;
  kind: CatalogKind;
  label: string;
  /** The entity's name: the initials fallback and the image's alt text. */
  name: string;
  value: string;
  /** The uploaded image's public URL, or `""` once the admin removes it. */
  onChange: (imagePath: string) => void;
  /** A portrait's circle, or a rounded frame `width` px wide (a map's landscape). */
  shape?: "circle" | "rounded";
  width?: number;
}

/**
 * Uploads the picked file to our bucket at once and hands its URL to the form; saving the dialog stores it.
 * A bucket URL survives the catalog sync, which only replaces images that still point at the source.
 */
export function CatalogImageField({
  discipline,
  kind,
  label,
  name,
  value,
  onChange,
  shape = "rounded",
  width,
}: Readonly<CatalogImageFieldProps>) {
  const t = useTranslations("adminWorkspace.content.fields");
  // ponytail: a dialog cancelled after an upload leaves the file orphaned in the bucket; sweep if it ever matters.
  const upload = useMutation({
    mutationFn: (file: File) => adminService.uploadCatalogImage(discipline, kind, file),
    onSuccess: ({ public_url }) => onChange(public_url),
    onError: (error) => notify.apiError(error, { title: t("imageUploadError") }),
  });
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <EditableAvatar
        src={value || null}
        name={name}
        size={64}
        width={width}
        shape={shape}
        busy={upload.isPending}
        onSelectFile={(file) => upload.mutate(file)}
        onDelete={() => onChange("")}
        maxSizeBytes={MAX_CATALOG_IMAGE_BYTES}
        onError={(message) => notify.error(message)}
      />
      <p className="text-xs text-muted-foreground">{t("imageHelp")}</p>
    </div>
  );
}

interface CatalogAliasesFieldProps {
  id: string;
  aliases: string[] | undefined;
  onChange: (aliases: string[]) => void;
  /** Helper copy under the textarea — a plain sentence or a richer fragment. */
  helperText: ReactNode;
}

export function CatalogAliasesField({ id, aliases, onChange, helperText }: Readonly<CatalogAliasesFieldProps>) {
  const t = useTranslations("adminWorkspace.content.fields");
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{t("aliases")}</Label>
      <Textarea
        id={id}
        value={formatAliasesInput(aliases ?? [])}
        onChange={(e) => onChange(parseAliasesInput(e.target.value))}
        rows={5}
      />
      <p className="text-xs text-muted-foreground">{helperText}</p>
    </div>
  );
}
