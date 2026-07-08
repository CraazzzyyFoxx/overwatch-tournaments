import { useEffect } from "react";
import type { RegistrationForm } from "@/types/registration.types";
import { cn } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { useTranslations } from "next-intl";
import CustomField from "./CustomField";
import FieldLabel from "./FieldLabel";
import { getBuiltInFieldValidationError } from "./validation";
import { BadgeInfo } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface DetailsStepProps {
  values: Record<string, string>;
  onUpdate: (key: string, value: string) => void;
  onFieldValidationChange: (fieldKey: string, error: string | null) => void;
  form: RegistrationForm;
  mode?: "public" | "admin";
  adminNotes?: string;
  onAdminNotesChange?: (v: string) => void;
  status?: string;
  onStatusChange?: (v: string) => void;
  balancerStatus?: string;
  onBalancerStatusChange?: (v: string) => void;
  registrationStatusOptions?: {
    system: Array<{ value: string; name: string }>;
    custom: Array<{ value: string; name: string }>;
  };
  balancerStatusOptions?: {
    system: Array<{ value: string; name: string }>;
    custom: Array<{ value: string; name: string }>;
  };
}

export default function DetailsStep({
  values,
  onUpdate,
  onFieldValidationChange,
  form,
  mode = "public",
  adminNotes,
  onAdminNotesChange,
  status,
  onStatusChange,
  balancerStatus,
  onBalancerStatusChange,
  registrationStatusOptions,
  balancerStatusOptions,
}: DetailsStepProps) {
  const t = useTranslations();
  const fields = form.built_in_fields;
  const showNotes = fields?.notes?.enabled !== false;
  const showStreamPov = fields?.stream_pov?.enabled === true;
  const notesValidationError = showNotes ? getBuiltInFieldValidationError(
    "notes",
    values.notes ?? "",
    fields?.notes,
    t,
  ) : null;

  useEffect(() => {
    onFieldValidationChange("notes", notesValidationError);
  }, [notesValidationError, onFieldValidationChange]);

  const hasCustomFields = form.custom_fields.length > 0;
  const hasAnyField = showNotes || showStreamPov || (mode === "public" && hasCustomFields);

  return (
    <div className="grid gap-4">
      <div className="space-y-1">
        <h3 className="text-xs font-medium uppercase tracking-[0.14em] text-white/55">
          {mode === "admin" ? "Details and Notes" : t("registration.details.title")}
        </h3>
        <p className="text-xs leading-5 text-white/42">
          {mode === "admin"
            ? "Final step for notes and status updates."
            : hasAnyField
              ? t("registration.details.descWithFields")
              : t("registration.details.descNoFields")}
        </p>
      </div>

      {showStreamPov && (
        <div className="space-y-2">
          <FieldLabel
            label={mode === "admin" ? "Stream POV" : t("registration.details.streamPov")}
            required={fields?.stream_pov?.required === true}
          />
          <label className="flex items-center gap-3">
            <Switch
              checked={values.stream_pov === "true"}
              onCheckedChange={(checked) => onUpdate("stream_pov", checked ? "true" : "false")}
            />
            <span className="text-sm text-white/70">
              {mode === "admin"
                ? "Participant can provide a point-of-view stream."
                : t("registration.details.streamPovLabel")}
            </span>
          </label>
        </div>
      )}

      {showNotes && (
        <div className="space-y-1.5">
          <FieldLabel
            label={mode === "admin" ? "Public Notes" : t("registration.details.notes")}
            required={fields?.notes?.required === true}
          />
          <textarea
            placeholder={mode === "admin" ? "Visible notes for balancer-facing context" : t("registration.details.notesPlaceholder")}
            value={values.notes ?? ""}
            onChange={(e) => onUpdate("notes", e.target.value)}
            rows={2}
            className={cn(
              "w-full rounded-lg border border-white/10 bg-white/3 px-3 py-2 text-sm text-white placeholder-white/30 outline-none transition-colors focus:border-white/20",
              notesValidationError && "border-red-500/70 text-red-100 placeholder:text-red-200/60 focus:border-red-500/70",
            )}
          />
          {notesValidationError && (
            <p className="text-xs text-red-400">{notesValidationError}</p>
          )}
        </div>
      )}

      {mode === "admin" && onAdminNotesChange && (
        <div className="space-y-1.5">
          <FieldLabel label="Admin Notes" icon={<BadgeInfo className="size-3.5 opacity-50" />} />
          <textarea
            placeholder="Internal notes for admins only"
            value={adminNotes ?? ""}
            onChange={(e) => onAdminNotesChange(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-white/10 bg-white/3 px-3 py-2 text-sm text-white placeholder-white/30 outline-none transition-colors focus:border-white/20"
          />
        </div>
      )}

      {mode === "admin" && onStatusChange && registrationStatusOptions && (
        <div className="space-y-1.5">
          <FieldLabel label="Registration Status" icon={<BadgeInfo className="size-3.5 opacity-50" />} />
          <Select value={status ?? "pending"} onValueChange={onStatusChange}>
            <SelectTrigger className="h-9 w-full rounded-lg border border-white/10 bg-white/3 px-3 text-sm text-white focus-visible:ring-0 focus-visible:border-white/20">
              <SelectValue placeholder="Select registration status" />
            </SelectTrigger>
            <SelectContent>
              {registrationStatusOptions.system.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.name} · System
                </SelectItem>
              ))}
              {registrationStatusOptions.custom.length > 0
                ? registrationStatusOptions.custom.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.name} · Custom
                    </SelectItem>
                  ))
                : null}
            </SelectContent>
          </Select>
        </div>
      )}

      {mode === "admin" && onBalancerStatusChange && balancerStatusOptions && (
        <div className="space-y-1.5">
          <FieldLabel label="Balancer Status" icon={<BadgeInfo className="size-3.5 opacity-50" />} />
          <Select value={balancerStatus ?? "not_in_balancer"} onValueChange={onBalancerStatusChange}>
            <SelectTrigger className="h-9 w-full rounded-lg border border-white/10 bg-white/3 px-3 text-sm text-white focus-visible:ring-0 focus-visible:border-white/20">
              <SelectValue placeholder="Select balancer status" />
            </SelectTrigger>
            <SelectContent>
              {balancerStatusOptions.system.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.name} · System
                </SelectItem>
              ))}
              {balancerStatusOptions.custom.length > 0
                ? balancerStatusOptions.custom.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.name} · Custom
                    </SelectItem>
                  ))
                : null}
            </SelectContent>
          </Select>
        </div>
      )}

      {mode === "public" && form.custom_fields.map((field) => (
        <CustomField
          key={field.key}
          definition={field}
          value={values[field.key] ?? ""}
          onChange={(v) => onUpdate(field.key, v)}
          onValidationChange={(error) => onFieldValidationChange(field.key, error)}
        />
      ))}
    </div>
  );
}

