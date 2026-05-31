"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import type { AdminCustomFieldDef } from "@/types/balancer-admin.types";

import { FIELD_TYPE_OPTIONS, getCustomFieldDefaultValidation, supportsCustomFieldValidation } from "./formConfig";

export function CustomFieldsCard({
  customFields,
  onAdd,
  onUpdate,
  onRemove,
}: {
  customFields: AdminCustomFieldDef[];
  onAdd: () => void;
  onUpdate: (index: number, updates: Partial<AdminCustomFieldDef>) => void;
  onRemove: (index: number) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>Custom Fields</CardTitle>
            <CardDescription>Add extra fields like Boosty nick, VK link, YouTube, etc.</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={onAdd}>
            <Plus className="mr-1.5 size-3.5" />
            Add field
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {customFields.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border/60 py-10 text-center">
            <p className="text-sm text-muted-foreground">No custom fields yet.</p>
            <p className="mt-1 text-xs text-muted-foreground/60">
              Click &quot;Add field&quot; to create fields like Boosty, VK, YouTube, etc.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {customFields.map((field, index) => (
              <div key={field.key || index} className="rounded-lg border p-4">
                <div className="grid gap-3 sm:grid-cols-[1fr_140px_140px_auto]">
                  <div className="space-y-1.5">
                    <Label className="text-xs">Label</Label>
                    <Input
                      value={field.label}
                      onChange={(e) => onUpdate(index, { label: e.target.value })}
                      placeholder="e.g. Boosty nick"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Type</Label>
                    <Select
                      value={field.type}
                      onValueChange={(v) => onUpdate(index, { type: v as AdminCustomFieldDef["type"] })}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {FIELD_TYPE_OPTIONS.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value}>
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs">Placeholder</Label>
                    <Input
                      value={field.placeholder ?? ""}
                      onChange={(e) => onUpdate(index, { placeholder: e.target.value || null })}
                      placeholder="Hint text..."
                    />
                  </div>
                  <div className="flex items-end gap-2">
                    <div className="flex items-center gap-2 rounded-lg border px-3 py-2">
                      <Switch
                        checked={field.required}
                        onCheckedChange={(checked) => onUpdate(index, { required: checked })}
                      />
                      <Label className="whitespace-nowrap text-xs text-muted-foreground">Required</Label>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="size-9 shrink-0 text-destructive hover:text-destructive"
                      onClick={() => onRemove(index)}
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
                {field.type === "select" && (
                  <div className="mt-3 space-y-1.5">
                    <Label className="text-xs">Options (one per line)</Label>
                    <textarea
                      className="w-full rounded-md border bg-transparent px-3 py-2 text-sm"
                      rows={3}
                      value={(field.options ?? []).join("\n")}
                      onChange={(e) =>
                        onUpdate(index, {
                          options: e.target.value.split("\n").filter((l) => l.trim()),
                        })
                      }
                      placeholder={"Option A\nOption B\nOption C"}
                    />
                  </div>
                )}
                {supportsCustomFieldValidation(field.type) && (
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Regex pattern</Label>
                      <Input
                        value={field.validation?.regex ?? ""}
                        onChange={(e) =>
                          onUpdate(index, {
                            validation: { ...field.validation, regex: e.target.value || null },
                          })
                        }
                        placeholder={getCustomFieldDefaultValidation(field.type)?.regex ?? "^[a-z0-9_]{3,}$"}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Error message</Label>
                      <Input
                        value={field.validation?.error_message ?? ""}
                        onChange={(e) =>
                          onUpdate(index, {
                            validation: { ...field.validation, error_message: e.target.value || null },
                          })
                        }
                        placeholder={
                          getCustomFieldDefaultValidation(field.type)?.error_message
                          ?? `Shown when ${field.label || "field"} is invalid`
                        }
                      />
                    </div>
                  </div>
                )}
                {field.key && (
                  <p className="mt-2 font-mono text-[10px] text-muted-foreground/50">key: {field.key}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
