"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { DateTimePicker } from "@/components/ui/date-picker";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { AnnouncementCreateBody } from "@/types/notification.types";

import {
  ANNOUNCEMENT_LOCALES,
  emptyAnnouncementDraft,
  filledLocales,
  validateAnnouncementDraft,
  type AnnouncementAudience,
  type AnnouncementDraft,
  type AnnouncementDraftError,
  type AnnouncementLocale,
} from "./announcement-draft";

interface AnnouncementFormProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Owned by the page: the feed on screen and the audience written are one choice. */
  audience: AnnouncementAudience;
  workspaceId: number | null;
  isPublishing: boolean;
  onPublish: (body: AnnouncementCreateBody) => void;
}

/**
 * Compose one announcement, one tab per locale.
 *
 * An `EntityFormDialog` like every other create surface in the admin: a list
 * screen is its table, and the composer arrives from the toolbar's primary
 * action. It used to be a card permanently open above the table, which pushed
 * the feed below the fold on the screen whose whole job is showing it, and was
 * the one admin form not in the dialog language.
 *
 * Tabs rather than two stacked forms because the locales are alternatives, not
 * sections: only one of them is ever read by any given visitor, and stacking
 * them reads as "fill both" even where one is enough.
 *
 * Every rule the operator can break is decided by `validateAnnouncementDraft`,
 * including which fallback locales this form is allowed to offer — the dialog
 * refuses for exactly the reason the server would, and says which.
 */
export function AnnouncementForm({
  open,
  onOpenChange,
  audience,
  workspaceId,
  isPublishing,
  onPublish,
}: Readonly<AnnouncementFormProps>) {
  const t = useTranslations<never>();
  const [form, setForm] = useState(() => emptyAnnouncementDraft(audience, workspaceId));
  const [tab, setTab] = useState<AnnouncementLocale>(ANNOUNCEMENT_LOCALES[0]);
  const [error, setError] = useState<AnnouncementDraftError | null>(null);

  // The audience lives on the page, so it is merged in rather than mirrored:
  // a copy here would need syncing, and a stale one would validate the draft
  // against the wrong locale rule.
  const draft: AnnouncementDraft = { ...form, audience, workspaceId };
  const filled = filledLocales(draft);

  const setLocaleText = (locale: AnnouncementLocale, field: "title" | "body", value: string) => {
    setError(null);
    setForm((current) => ({
      ...current,
      locales: { ...current.locales, [locale]: { ...current.locales[locale], [field]: value } },
    }));
  };

  const onSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const result = validateAnnouncementDraft(draft);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    setError(null);
    onPublish(result.body);
  };

  return (
    <EntityFormDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("notifications.admin.form.title")}
      description={
        audience === "global"
          ? t("notifications.admin.form.globalHint")
          : t("notifications.admin.form.workspaceHint")
      }
      onSubmit={onSubmit}
      submitLabel={t("notifications.admin.form.publish")}
      submittingLabel={t("notifications.admin.form.publishing")}
      cancelLabel={t("notifications.admin.form.cancel")}
      isSubmitting={isPublishing}
      isDirty={filled.length > 0 || form.href !== "" || form.publishedAt !== "" || form.expiresAt !== ""}
      errorMessage={error ? t(`notifications.admin.errors.${error}`) : undefined}
    >
      <Tabs value={tab} onValueChange={(next) => setTab(next as AnnouncementLocale)}>
        <TabsList>
          {ANNOUNCEMENT_LOCALES.map((locale) => (
            <TabsTrigger key={locale} value={locale} data-field={`locale-tab-${locale}`}>
              {t(`notifications.admin.locales.${locale}`)}
              {filled.includes(locale) ? null : (
                <span className="ml-1.5 text-xs text-muted-foreground">
                  {t("notifications.admin.form.localeEmpty")}
                </span>
              )}
            </TabsTrigger>
          ))}
        </TabsList>
        {ANNOUNCEMENT_LOCALES.map((locale) => (
          <TabsContent key={locale} value={locale} className="flex flex-col gap-4 pt-4">
            <div>
              <Label htmlFor={`announcement-title-${locale}`}>
                {t("notifications.admin.form.titleField")}
              </Label>
              <Input
                id={`announcement-title-${locale}`}
                data-field={`title-${locale}`}
                className="mt-1.5"
                maxLength={200}
                value={form.locales[locale].title}
                onChange={(event) => setLocaleText(locale, "title", event.target.value)}
              />
            </div>
            <div>
              <Label htmlFor={`announcement-body-${locale}`}>
                {t("notifications.admin.form.bodyField")}
              </Label>
              <Textarea
                id={`announcement-body-${locale}`}
                data-field={`body-${locale}`}
                className="mt-1.5"
                maxLength={4000}
                rows={4}
                value={form.locales[locale].body}
                onChange={(event) => setLocaleText(locale, "body", event.target.value)}
              />
            </div>
          </TabsContent>
        ))}
      </Tabs>

      <div>
        <p className="text-sm font-medium leading-none">
          {t("notifications.admin.form.defaultLocale")}
        </p>
        {/* Offered from the same `filledLocales` the validator reads, so
            "default_locale has no text" is unreachable rather than merely
            caught. Nothing written yet means nothing to choose between. */}
        <div className="mt-1.5" data-field="default-locale">
          {filled.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("notifications.admin.form.defaultLocaleEmpty")}
            </p>
          ) : (
            <ToggleGroup
              type="single"
              value={filled.includes(form.defaultLocale) ? form.defaultLocale : ""}
              onValueChange={(next) =>
                setForm((current) => ({ ...current, defaultLocale: next as AnnouncementLocale }))
              }
              aria-label={t("notifications.admin.form.defaultLocale")}
            >
              {filled.map((locale) => (
                <ToggleGroupItem key={locale} value={locale}>
                  {t(`notifications.admin.locales.${locale}`)}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          )}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {t("notifications.admin.form.defaultLocaleHint")}
        </p>
      </div>

      <div>
        <Label htmlFor="announcement-href">{t("notifications.admin.form.href")}</Label>
        <Input
          id="announcement-href"
          data-field="href"
          className="mt-1.5"
          maxLength={512}
          placeholder="/tournaments"
          value={form.href}
          onChange={(event) => setForm((current) => ({ ...current, href: event.target.value }))}
        />
      </div>

      {/* Wall-clock decisions, so the value stays a local "YYYY-MM-DDTHH:mm"
          string — `instant()` parses it. The house picker rather than the
          native control: it speaks the UI locale (the browser's follows its
          own), and its calendar and time field are the ones every other
          schedule form in the admin uses. */}
      <div className="grid gap-4 sm:grid-cols-2">
        <DateTimePicker
          id="announcement-published-at"
          timeId="announcement-published-at-time"
          dateLabel={t("notifications.admin.form.publishedAt")}
          timeLabel={t("notifications.admin.form.publishedAtTime")}
          clearLabel={t("notifications.admin.form.scheduleClear")}
          placeholder={t("notifications.admin.form.publishedAtPlaceholder")}
          value={form.publishedAt}
          onChange={(value) => setForm((current) => ({ ...current, publishedAt: value }))}
          disabled={isPublishing}
        />
        <DateTimePicker
          id="announcement-expires-at"
          timeId="announcement-expires-at-time"
          dateLabel={t("notifications.admin.form.expiresAt")}
          timeLabel={t("notifications.admin.form.expiresAtTime")}
          clearLabel={t("notifications.admin.form.scheduleClear")}
          placeholder={t("notifications.admin.form.expiresAtPlaceholder")}
          value={form.expiresAt}
          onChange={(value) => setForm((current) => ({ ...current, expiresAt: value }))}
          disabled={isPublishing}
        />
      </div>
    </EntityFormDialog>
  );
}
