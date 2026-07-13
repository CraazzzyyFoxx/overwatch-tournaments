import Image from "next/image";
import { Globe } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { OAuthProvider } from "@/types/rbac.types";

export const PROVIDER_META: Record<
  OAuthProvider,
  { label: string; icon: string | null; iconClass?: string }
> = {
  discord: { label: "Discord", icon: "/discord.png" },
  twitch: { label: "Twitch", icon: "/twitch.png" },
  battlenet: { label: "Battle.net", icon: "/battlenet.svg", iconClass: "invert grayscale" },
  google: { label: "Google", icon: null },
  github: { label: "GitHub", icon: null }
};

const PROVIDER_COLORS: Record<OAuthProvider, string> = {
  discord: "bg-[#5865F2]/15 text-[#7289da] border-[#5865F2]/30",
  twitch: "bg-[#9146FF]/15 text-[#b380ff] border-[#9146FF]/30",
  battlenet: "bg-[#148EFF]/15 text-[#60b0ff] border-[#148EFF]/30",
  google: "bg-red-500/15 text-red-400 border-red-500/30",
  github: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30"
};

export function ProviderBadge({ provider }: { provider: OAuthProvider }) {
  const meta = PROVIDER_META[provider];
  return (
    <Badge variant="outline" className={`gap-1.5 ${PROVIDER_COLORS[provider]}`}>
      {meta?.icon ? (
        <Image
          src={meta.icon}
          alt={meta.label}
          width={14}
          height={14}
          className={meta.iconClass ?? ""}
        />
      ) : (
        <Globe className="h-3.5 w-3.5" />
      )}
      {meta?.label ?? provider}
    </Badge>
  );
}
