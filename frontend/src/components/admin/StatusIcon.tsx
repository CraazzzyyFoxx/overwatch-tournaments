import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

type StatusVariant = "default" | "muted" | "success" | "destructive" | "warning" | "info";

const variantColors: Record<StatusVariant, string> = {
  default: "text-foreground",
  muted: "text-muted-foreground",
  success: "text-emerald-500",
  destructive: "text-destructive",
  warning: "text-amber-500",
  info: "text-blue-400",
};

interface StatusIconProps {
  icon: LucideIcon;
  label: string;
  variant?: StatusVariant;
  className?: string;
}

export function StatusIcon({ icon: Icon, label, variant = "default", className }: StatusIconProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-default" aria-label={label}>
          <Icon className={cn("size-4", variantColors[variant], className)} />
        </span>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}
