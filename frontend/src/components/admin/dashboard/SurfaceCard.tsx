import type { ComponentProps } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function SurfaceCard({ className, ...props }: ComponentProps<typeof Card>) {
  return (
    <Card
      data-ui="card"
      className={cn("rounded-2xl border-border/50 bg-card/72 shadow-sm", className)}
      {...props}
    />
  );
}
