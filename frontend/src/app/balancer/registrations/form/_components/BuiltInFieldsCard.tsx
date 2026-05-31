"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import type { BuiltInFieldConfig } from "@/types/balancer-admin.types";

import { BUILT_IN_FIELDS } from "./formConfig";

export function BuiltInFieldsCard({
  builtInFields,
  onUpdate,
}: {
  builtInFields: Record<string, BuiltInFieldConfig>;
  onUpdate: (key: string, updates: Partial<BuiltInFieldConfig>) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Built-in Fields</CardTitle>
        <CardDescription>
          Toggle which standard fields appear on the registration form. Sub-roles for the role
          fields are configured in the Subroles tab.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="divide-y rounded-lg border">
          {BUILT_IN_FIELDS.map((def) => {
            const cfg = builtInFields[def.key] ?? { enabled: def.defaultEnabled, required: def.defaultRequired };
            return (
              <div key={def.key} className="px-4 py-3">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium">{def.label}</span>
                      {cfg.required && cfg.enabled && (
                        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-semibold text-primary">
                          Required
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">{def.description}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-4">
                    {cfg.enabled && (
                      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <Switch
                          checked={cfg.required}
                          onCheckedChange={(checked) => onUpdate(def.key, { required: checked })}
                          className="scale-75"
                        />
                        Required
                      </label>
                    )}
                    <Switch
                      checked={cfg.enabled}
                      onCheckedChange={(checked) =>
                        onUpdate(def.key, { enabled: checked, ...(checked ? {} : { required: false }) })
                      }
                    />
                  </div>
                </div>
                {def.supportsValidation && cfg.enabled && (
                  <div className="mt-3 grid gap-3 rounded-md border border-dashed border-border/60 p-3 md:grid-cols-2">
                    <div className="space-y-1.5">
                      <Label className="text-xs">Regex pattern</Label>
                      <Input
                        value={cfg.validation?.regex ?? ""}
                        onChange={(e) =>
                          onUpdate(def.key, {
                            validation: {
                              ...cfg.validation,
                              regex: e.target.value || null,
                            },
                          })
                        }
                        placeholder={def.defaultValidation?.regex ?? "^[a-z0-9_]+$"}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label className="text-xs">Error message</Label>
                      <Input
                        value={cfg.validation?.error_message ?? ""}
                        onChange={(e) =>
                          onUpdate(def.key, {
                            validation: {
                              ...cfg.validation,
                              error_message: e.target.value || null,
                            },
                          })
                        }
                        placeholder={`Shown when ${def.label} is invalid`}
                      />
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}
