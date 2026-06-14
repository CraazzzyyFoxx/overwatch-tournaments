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
                <div className="grid gap-4 items-center grid-cols-1 md:grid-cols-[220px_1fr_1.2fr_180px]">
                  {/* Column 1: Label & Description */}
                  <div className="min-w-0">
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

                  {/* Column 2: Regex or Max Heroes */}
                  <div className="min-w-0">
                    {cfg.enabled && def.supportsValidation && (
                      <div className="space-y-1">
                        <Label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
                          Regex pattern
                        </Label>
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
                          className="h-8 text-xs bg-background/50"
                        />
                      </div>
                    )}
                    {cfg.enabled && def.supportsMaxHeroes && (
                      <div className="space-y-1">
                        <Label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
                          Max heroes per role
                        </Label>
                        <Input
                          type="number"
                          min={1}
                          max={20}
                          value={cfg.max_heroes ?? ""}
                          onChange={(e) => {
                            const parsed = parseInt(e.target.value, 10);
                            onUpdate(def.key, {
                              max_heroes: Number.isFinite(parsed) && parsed > 0 ? parsed : null,
                            });
                          }}
                          placeholder="5"
                          className="h-8 text-xs bg-background/50"
                        />
                      </div>
                    )}
                  </div>

                  {/* Column 3: Error Message */}
                  <div className="min-w-0">
                    {cfg.enabled && def.supportsValidation && (
                      <div className="space-y-1">
                        <Label className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/75">
                          Error message
                        </Label>
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
                          className="h-8 text-xs bg-background/50"
                        />
                      </div>
                    )}
                  </div>

                  {/* Column 4: Controls */}
                  <div className="flex items-center justify-end gap-3 justify-self-end">
                    {cfg.enabled && def.supportsRequired !== false && (
                      <label className="flex items-center gap-1.5 text-xs text-muted-foreground select-none cursor-pointer">
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
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}


