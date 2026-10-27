"use client";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn, initials } from "@/lib/utils";

export function GuildMark({
  name,
  src,
  size
}: Readonly<{ name: string; src?: string | null; size: "md" | "lg" }>) {
  return (
    <Avatar className={cn("rounded-lg border", size === "lg" ? "size-12" : "size-9")}>
      {src ? <AvatarImage src={src} alt="" /> : null}
      <AvatarFallback className="rounded-lg">
        {initials(name)}
      </AvatarFallback>
    </Avatar>
  );
}
