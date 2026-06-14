"use client";

import Link from "next/link";
import { Plus, Upload } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuthProfile } from "@/hooks/useAuthProfile";
import { useWorkspaceStore } from "@/stores/workspace.store";

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

interface GreetingBarProps {
  canCreateTournament?: boolean;
}

export function GreetingBar({ canCreateTournament }: GreetingBarProps) {
  const { user } = useAuthProfile();
  const { workspaces, currentWorkspaceId } = useWorkspaceStore();
  const currentWorkspace = workspaces.find((w) => w.id === currentWorkspaceId);

  const greeting = getGreeting();
  const displayName = user?.username ?? "Admin";

  return (
    <div className="flex items-center justify-between gap-4">
      <div className="flex items-center gap-3 min-w-0">
        <div className="min-w-0">
          <h1 className="text-lg font-medium text-foreground truncate">
            {greeting}, {displayName}
          </h1>
          <p className="text-xs text-muted-foreground">
            {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </p>
        </div>
        {currentWorkspace && (
          <Badge variant="outline" className="rounded-full px-2.5 py-0.5 text-[10px] uppercase tracking-widest text-muted-foreground shrink-0">
            {currentWorkspace.name}
          </Badge>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {canCreateTournament && (
          <Button asChild variant="outline" size="sm">
            <Link href="/admin/tournaments">
              <Plus className="size-3.5" />
              New Tournament
            </Link>
          </Button>
        )}
      </div>
    </div>
  );
}
