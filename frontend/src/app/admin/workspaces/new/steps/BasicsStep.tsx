"use client";

import { useTranslations } from "next-intl";

import { EditableAvatar } from "@/components/ui/editable-avatar";
import { Input } from "@/components/ui/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText
} from "@/components/ui/input-group";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { notify } from "@/lib/notify";
import { PLATFORM_ZONE } from "@/lib/site/host";
import { cn } from "@/lib/utils";
import { suggestSlug } from "@/lib/workspace/slug";

const ACCEPTED_IMAGE_TYPES = "image/webp,image/png,image/jpeg,image/gif";
const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2 MB

export interface BasicsValue {
  name: string;
  slug: string;
  /** Set once the slug is typed by hand; until then it follows the name. */
  slugTouched: boolean;
  description: string;
  /** A picked file waiting for the workspace to exist: the icon has its own endpoint. */
  icon: { file: File; preview: string } | null;
}

/**
 * Step 1: the name and the platform address, then the icon and description.
 *
 * `locked` is basics revisited after Create: the workspace exists, and its
 * slug is not something the PATCH can change.
 */
export function BasicsStep({
  value,
  onChange,
  locked,
  iconSrc,
  errors
}: Readonly<{
  value: BasicsValue;
  onChange: (next: BasicsValue) => void;
  locked: boolean;
  iconSrc: string | null;
  errors: { name?: string; slug?: string; form?: string };
}>) {
  const t = useTranslations("adminWorkspace.newWorkspace.basics");

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Label htmlFor="workspace-name">{t("name")}</Label>
        <Input
          id="workspace-name"
          className="mt-1.5"
          value={value.name}
          placeholder={t("namePlaceholder")}
          autoComplete="off"
          aria-invalid={Boolean(errors.name)}
          aria-describedby={errors.name ? "workspace-name-error" : undefined}
          onChange={(event) => {
            const name = event.target.value;
            onChange({
              ...value,
              name,
              slug: locked || value.slugTouched ? value.slug : suggestSlug(name)
            });
          }}
        />
        {errors.name ? (
          <p id="workspace-name-error" className="mt-1 text-xs text-danger">
            {errors.name}
          </p>
        ) : null}
      </div>

      <div>
        <Label htmlFor="workspace-slug">{t("address")}</Label>
        <InputGroup className="mt-1.5">
          <InputGroupAddon className="max-w-[60%]">
            <InputGroupText className="block truncate font-mono">
              {PLATFORM_ZONE}/workspace/
            </InputGroupText>
          </InputGroupAddon>
          <InputGroupInput
            id="workspace-slug"
            className="font-mono"
            value={value.slug}
            disabled={locked}
            spellCheck={false}
            autoComplete="off"
            aria-invalid={Boolean(errors.slug)}
            aria-describedby="workspace-slug-help"
            onChange={(event) => {
              const slug = event.target.value.toLowerCase();
              // Clearing the field hands it back to the name.
              onChange({ ...value, slug, slugTouched: slug !== "" });
            }}
          />
        </InputGroup>
        <p
          id="workspace-slug-help"
          className={cn("mt-1 text-xs", errors.slug ? "text-danger" : "text-muted-foreground")}
        >
          {errors.slug ?? (locked ? t("addressLocked") : t("addressHelp"))}
        </p>
      </div>

      <div>
        <p className="text-sm font-medium leading-none">{t("icon")}</p>
        <div className="mt-1.5">
          <EditableAvatar
            src={value.icon?.preview ?? iconSrc}
            name={value.name}
            size={64}
            shape="rounded"
            onSelectFile={(file) =>
              onChange({ ...value, icon: { file, preview: URL.createObjectURL(file) } })
            }
            onDelete={value.icon ? () => onChange({ ...value, icon: null }) : undefined}
            accept={ACCEPTED_IMAGE_TYPES}
            maxSizeBytes={MAX_FILE_SIZE}
            onError={(message) => notify.error(message)}
          />
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{t("iconHelp")}</p>
      </div>

      <div>
        <Label htmlFor="workspace-description">{t("description")}</Label>
        <Textarea
          id="workspace-description"
          className="mt-1.5"
          value={value.description}
          onChange={(event) => onChange({ ...value, description: event.target.value })}
        />
        <p className="mt-1 text-xs text-muted-foreground">{t("descriptionHelp")}</p>
      </div>

      {errors.form ? (
        <p role="alert" className="text-sm font-medium text-danger">
          {errors.form}
        </p>
      ) : null}
    </div>
  );
}
