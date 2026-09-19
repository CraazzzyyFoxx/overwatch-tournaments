"use client";

import type { CSSProperties } from "react";

import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { SaveBar } from "@/components/kit/SaveBar";
import { deriveWorkspacePalette } from "@/lib/workspace-theme";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

function BrandColorField({
  id,
  label,
  value,
  onChange
}: Readonly<{
  id: string;
  label: string;
  value: string | null | undefined;
  onChange: (value: string) => void;
}>) {
  const hex = value ?? "";
  const valid = /^#[0-9a-fA-F]{6}$/.test(hex);
  // Both hexes below are exempt from the design-token rule: `<input type="color">`
  // only accepts a literal `#rrggbb` (it cannot resolve a CSS variable), and the
  // text field's placeholder just shows that expected shape. Neither paints
  // chrome — the value they carry is the workspace's own persisted brand colour.
  return (
    <div>
      <Label htmlFor={id}>{label}</Label>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="color"
          aria-label={`${label} colour picker`}
          value={valid ? hex : "#000000"}
          onChange={(event) => onChange(event.target.value)}
          className="h-9 w-10 shrink-0 cursor-pointer rounded border border-input bg-transparent p-0.5"
        />
        <Input
          id={id}
          value={hex}
          onChange={(event) => onChange(event.target.value)}
          placeholder="#000000"
          className="font-mono"
        />
      </div>
    </div>
  );
}

/**
 * The workspace's public-site palette: four seed colours, six optional
 * overrides, and a preview of what they derive to.
 */
export function BrandingSection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const settings = useWorkspaceSettingsForm(workspaceId, "branding");
  const { form, patch } = settings;

  // The preview always renders as if branding were on, so the palette can be
  // judged before the switch commits it to the public site.
  const preview = form ? deriveWorkspacePalette({ ...form, branding_enabled: true }) : null;

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ form: values }) => (
        <>
          <Card>
            <CardContent className="flex flex-col gap-4 pt-6">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <Label htmlFor="branding-enabled">Site branding</Label>
                  <p className="text-xs text-muted-foreground">
                    Custom palette for this workspace on the main public site
                  </p>
                </div>
                <Switch
                  id="branding-enabled"
                  checked={values.branding_enabled}
                  onCheckedChange={(checked) => patch({ branding_enabled: checked })}
                />
              </div>

              <div>
                <h2 className={EYEBROW_CLASS}>Seed colours</h2>
                <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <BrandColorField
                    id="brand-primary"
                    label="Primary accent"
                    value={values.brand_primary}
                    onChange={(value) => patch({ brand_primary: value })}
                  />
                  <BrandColorField
                    id="brand-secondary"
                    label="Secondary accent"
                    value={values.brand_secondary}
                    onChange={(value) => patch({ brand_secondary: value })}
                  />
                  <BrandColorField
                    id="brand-background"
                    label="Background"
                    value={values.brand_background}
                    onChange={(value) => patch({ brand_background: value })}
                  />
                  <BrandColorField
                    id="brand-surface"
                    label="Surface"
                    value={values.brand_surface}
                    onChange={(value) => patch({ brand_surface: value })}
                  />
                </div>
              </div>

              <div>
                <h2 className={EYEBROW_CLASS}>Core palette · optional overrides</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  Leave blank to derive from the seed colours above.
                </p>
                <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <BrandColorField
                    id="brand-accent"
                    label="Accent"
                    value={values.brand_accent}
                    onChange={(value) => patch({ brand_accent: value })}
                  />
                  <BrandColorField
                    id="brand-foreground"
                    label="Foreground (text)"
                    value={values.brand_foreground}
                    onChange={(value) => patch({ brand_foreground: value })}
                  />
                  <BrandColorField
                    id="brand-muted"
                    label="Muted surface"
                    value={values.brand_muted}
                    onChange={(value) => patch({ brand_muted: value })}
                  />
                  <BrandColorField
                    id="brand-border"
                    label="Border"
                    value={values.brand_border}
                    onChange={(value) => patch({ brand_border: value })}
                  />
                  <BrandColorField
                    id="brand-ring"
                    label="Focus ring"
                    value={values.brand_ring}
                    onChange={(value) => patch({ brand_ring: value })}
                  />
                  <BrandColorField
                    id="brand-destructive"
                    label="Destructive"
                    value={values.brand_destructive}
                    onChange={(value) => patch({ brand_destructive: value })}
                  />
                </div>
              </div>

              {preview ? (
                <div
                  className="rounded-md border border-border p-3"
                  style={{ ...preview, background: "var(--aqt-bg)" } as CSSProperties}
                >
                  <p className="text-xs font-medium" style={{ color: "var(--aqt-fg)" }}>
                    Preview
                  </p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <span
                      className="rounded px-2 py-1 text-xs font-medium"
                      style={{
                        background: "var(--aqt-teal)",
                        color: "hsl(var(--primary-foreground))"
                      }}
                    >
                      Primary
                    </span>
                    <span
                      className="rounded px-2 py-1 text-xs font-medium"
                      style={{
                        background: "var(--aqt-violet)",
                        color: "hsl(var(--secondary-foreground))"
                      }}
                    >
                      Secondary
                    </span>
                    <span
                      className="rounded px-2 py-1 text-xs"
                      style={{
                        background: "var(--aqt-card)",
                        color: "var(--aqt-fg-muted)",
                        border: "1px solid var(--aqt-border)"
                      }}
                    >
                      Surface
                    </span>
                    <span
                      className="rounded px-2 py-1 text-xs font-medium"
                      style={{
                        background: "hsl(var(--destructive))",
                        color: "hsl(var(--destructive-foreground))"
                      }}
                    >
                      Destructive
                    </span>
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <SaveBar
            dirty={settings.dirty}
            summary={settings.summary}
            saving={settings.saving}
            onDiscard={settings.discard}
            onSave={settings.save}
          />
        </>
      )}
    </WorkspaceSettingsFrame>
  );
}
