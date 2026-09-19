"use client";

import { useId, useState } from "react";
import { ChevronDown, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { AdminCustomFieldDef } from "@/types/balancer-admin.types";

import { FIELD_TYPE_OPTIONS, getCustomFieldDefaultValidation, supportsCustomFieldValidation } from "./formConfig";
import { EmptyNote } from "@/components/kit/EmptyNote";

export function CustomFieldsCard({
  customFields,
  onAdd,
  onUpdate,
  onRemove,
}: Readonly<{
  customFields: AdminCustomFieldDef[];
  onAdd: () => void;
  onUpdate: (index: number, updates: Partial<AdminCustomFieldDef>) => void;
  onRemove: (index: number) => void;
}>) {
  const t = useTranslations("registrationFormAdmin.customFields");
  const idPrefix = useId();
  const [expandedFields, setExpandedFields] = useState<Record<number, boolean>>({});

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div>
            <CardTitle asChild>
              <h2>{t("title")}</h2>
            </CardTitle>
            <CardDescription className="max-w-prose">{t("description")}</CardDescription>
          </div>
          {/* While the list is empty the empty state owns this action, so the
              header does not show a second copy of the same button. */}
          {customFields.length > 0 && (
            <Button variant="outline" size="sm" className="shrink-0" onClick={onAdd}>
              <Plus className="mr-1.5 size-3.5" aria-hidden />
              {t("addField")}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {customFields.length === 0 ? (
          <EmptyNote
            title={t("emptyTitle")}
            action={
              <Button variant="outline" size="sm" onClick={onAdd}>
                <Plus className="mr-1.5 size-3.5" aria-hidden />
                {t("addField")}
              </Button>
            }
          >
            {t("emptyHint")}
          </EmptyNote>
        ) : (
          <div className="space-y-3">
            {customFields.map((field, index) => {
              const hasSettings =
                field.type === "select" || supportsCustomFieldValidation(field.type);
              const isExpanded = !!expandedFields[index];
              const fieldName = field.label || t("fieldFallback");
              const rowId = `${idPrefix}-${index}`;

              return (
                <div key={field.key || index} className="rounded-lg border p-4">
                  {/* Label and placeholder both hold free text, so both flex; only
                      the type picker has a fixed intrinsic width. */}
                  <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_150px_minmax(0,1fr)_auto]">
                    <div className="space-y-1.5">
                      <Label htmlFor={`${rowId}-label`} className="text-xs">
                        {t("label")}
                      </Label>
                      <Input
                        id={`${rowId}-label`}
                        value={field.label}
                        onChange={(e) => onUpdate(index, { label: e.target.value })}
                        placeholder={t("labelPlaceholder")}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`${rowId}-type`} className="text-xs">
                        {t("type")}
                      </Label>
                      <Select
                        value={field.type}
                        onValueChange={(v) => {
                          const nextType = v as AdminCustomFieldDef["type"];
                          onUpdate(index, { type: nextType });
                          const nextHasSettings =
                            nextType === "select" || supportsCustomFieldValidation(nextType);
                          if (nextHasSettings) {
                            setExpandedFields((prev) => ({ ...prev, [index]: true }));
                          }
                        }}
                      >
                        <SelectTrigger id={`${rowId}-type`}>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {FIELD_TYPE_OPTIONS.map((opt) => (
                            <SelectItem key={opt.value} value={opt.value}>
                              {t(`types.${opt.value}`)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`${rowId}-placeholder`} className="text-xs">
                        {t("placeholder")}
                      </Label>
                      <Input
                        id={`${rowId}-placeholder`}
                        value={field.placeholder ?? ""}
                        onChange={(e) => onUpdate(index, { placeholder: e.target.value || null })}
                        placeholder={t("placeholderHint")}
                      />
                    </div>
                    <div className="flex flex-wrap items-end gap-2">
                      <label
                        htmlFor={`${rowId}-required`}
                        className="flex h-9 cursor-pointer select-none items-center gap-2 rounded-lg border px-3 text-xs text-muted-foreground"
                      >
                        <Switch
                          id={`${rowId}-required`}
                          checked={field.required}
                          onCheckedChange={(checked) => onUpdate(index, { required: checked })}
                        />
                        <span className="whitespace-nowrap">{t("required")}</span>
                      </label>
                      {/* The draft board is public, so this is an explicit
                          per-field opt-in rather than a consequence of asking. */}
                      <label
                        htmlFor={`${rowId}-show-in-draft`}
                        title={t("showInDraftHint")}
                        className="flex h-9 cursor-pointer select-none items-center gap-2 rounded-lg border px-3 text-xs text-muted-foreground"
                      >
                        <Switch
                          id={`${rowId}-show-in-draft`}
                          checked={field.show_in_draft ?? false}
                          onCheckedChange={(checked) => onUpdate(index, { show_in_draft: checked })}
                        />
                        <span className="whitespace-nowrap">{t("showInDraft")}</span>
                      </label>
                      {hasSettings && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-9 shrink-0 text-muted-foreground hover:text-foreground"
                          aria-label={t("settingsAria", { field: fieldName })}
                          aria-expanded={isExpanded}
                          onClick={() =>
                            setExpandedFields((prev) => ({ ...prev, [index]: !prev[index] }))
                          }
                        >
                          <ChevronDown
                            className={cn(
                              "size-4 transition-transform duration-200",
                              isExpanded && "rotate-180 text-primary"
                            )}
                            aria-hidden
                          />
                        </Button>
                      )}
                      <Button
                        variant="ghost"
                        size="icon"
                        className="size-9 shrink-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                        aria-label={t("removeAria", { field: fieldName })}
                        onClick={() => onRemove(index)}
                      >
                        <Trash2 className="size-4" aria-hidden />
                      </Button>
                    </div>
                  </div>
                  {hasSettings && (
                    <Collapsible open={isExpanded}>
                      <CollapsibleContent className="overflow-hidden data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down">
                        {field.type === "select" && (
                          <div className="mt-3 space-y-1.5">
                            <Label htmlFor={`${rowId}-options`} className="text-xs">
                              {t("options")}
                            </Label>
                            <Textarea
                              id={`${rowId}-options`}
                              rows={3}
                              value={(field.options ?? []).join("\n")}
                              onChange={(e) =>
                                onUpdate(index, {
                                  options: e.target.value.split("\n").filter((l) => l.trim())
                                })
                              }
                              placeholder={t("optionsPlaceholder")}
                            />
                          </div>
                        )}
                        {supportsCustomFieldValidation(field.type) && (
                          <div className="mt-3 grid gap-3 md:grid-cols-2">
                            <div className="space-y-1.5">
                              <Label htmlFor={`${rowId}-regex`} className="text-xs">
                                {t("regex")}
                              </Label>
                              <Input
                                id={`${rowId}-regex`}
                                value={field.validation?.regex ?? ""}
                                onChange={(e) =>
                                  onUpdate(index, {
                                    validation: {
                                      ...field.validation,
                                      regex: e.target.value || null
                                    }
                                  })
                                }
                                placeholder={
                                  getCustomFieldDefaultValidation(field.type)?.regex ??
                                  "^[a-z0-9_]{3,}$"
                                }
                                spellCheck={false}
                                autoCapitalize="none"
                                className="font-mono"
                              />
                            </div>
                            <div className="space-y-1.5">
                              <Label htmlFor={`${rowId}-error`} className="text-xs">
                                {t("errorMessage")}
                              </Label>
                              <Input
                                id={`${rowId}-error`}
                                value={field.validation?.error_message ?? ""}
                                onChange={(e) =>
                                  onUpdate(index, {
                                    validation: {
                                      ...field.validation,
                                      error_message: e.target.value || null
                                    }
                                  })
                                }
                                placeholder={
                                  getCustomFieldDefaultValidation(field.type)?.error_message ??
                                  t("errorMessagePlaceholder", { field: fieldName })
                                }
                              />
                            </div>
                          </div>
                        )}
                      </CollapsibleContent>
                    </Collapsible>
                  )}
                  {field.key && (
                    <p className="mt-2 font-mono text-xs text-muted-foreground">
                      {t("keyLabel", { key: field.key })}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

