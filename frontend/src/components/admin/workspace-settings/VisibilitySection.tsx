"use client";

import { useTranslations } from "next-intl";
import { Label } from "@craazzzyyfoxx/admin-kit/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { SaveBar } from "@/components/kit/SaveBar";
import { SettingGroup, SettingRow, SettingsGrid } from "@/components/kit/SettingRow";
import { WorkspaceSettingsFrame } from "./WorkspaceSettingsFrame";
import { useWorkspaceSettingsForm } from "./useWorkspaceSettingsForm";

const NEWCOMER_SCOPES = [
  { value: "global", label: "platformWide", help: "platformWideHelp" },
  { value: "workspace", label: "workspaceOnly", help: "workspaceOnlyHelp" }
] as const;

/**
 * Who can find this workspace, and whose history counts when a roster decides
 * a player is new.
 *
 * Newcomer scope reads like a rating knob rather than a visibility one, but it
 * is the same question in reverse — how much of the platform this workspace
 * considers itself part of — and it has no other home. Its two options are
 * radios that each state their consequence: as a two-button toggle the
 * difference lived in one paragraph the reader had to map back onto them.
 */
export function VisibilitySection({ workspaceId }: Readonly<{ workspaceId: number | null }>) {
  const t = useTranslations("adminWorkspace.workspaceSettings.visibility");
  const settings = useWorkspaceSettingsForm(workspaceId, "visibility");
  const { patch } = settings;

  return (
    <WorkspaceSettingsFrame workspaceId={workspaceId} settings={settings}>
      {({ form: values }) => (
        <>
          <SettingsGrid>
            <SettingGroup id="listing" title={t("groups.discovery.title")}>
              <SettingRow htmlFor="workspace-is-hidden" label={t("hidden")} hint={t("hiddenHelp")}>
                <Switch
                  id="workspace-is-hidden"
                  checked={values.is_hidden}
                  onCheckedChange={(checked) => patch({ is_hidden: checked })}
                />
              </SettingRow>
            </SettingGroup>

            <SettingGroup
              id="newcomers"
              title={t("groups.newcomers.title")}
              description={t("scopeHelp")}
            >
              <RadioGroup
                value={values.newcomer_scope}
                onValueChange={(value) => patch({ newcomer_scope: value as "global" | "workspace" })}
                aria-label={t("newcomerScope")}
                className="gap-4"
              >
                {NEWCOMER_SCOPES.map((scope) => {
                  const id = `newcomer-scope-${scope.value}`;
                  return (
                    <div key={scope.value} className="flex items-start gap-3">
                      <RadioGroupItem
                        id={id}
                        value={scope.value}
                        aria-describedby={`${id}-help`}
                        className="mt-0.5"
                      />
                      <div className="min-w-0">
                        <Label htmlFor={id} className="text-sm font-medium">
                          {t(scope.label)}
                        </Label>
                        <p id={`${id}-help`} className="mt-0.5 max-w-prose text-xs text-muted-foreground">
                          {t(scope.help)}
                        </p>
                      </div>
                    </div>
                  );
                })}
              </RadioGroup>
            </SettingGroup>
          </SettingsGrid>

          <SaveBar
            dirty={settings.dirty}
            summary={settings.summary}
            error={settings.error}
            saving={settings.saving}
            onDiscard={settings.discard}
            onSave={settings.save}
          />
        </>
      )}
    </WorkspaceSettingsFrame>
  );
}
