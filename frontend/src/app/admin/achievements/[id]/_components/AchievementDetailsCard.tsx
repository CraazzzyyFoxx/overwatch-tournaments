"use client";

import { Hash, Trophy, Users } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { AchievementRule } from "@/types/admin.types";

import { CategoryIcon, GrainIcon, ScopeIcon } from "../../achievement-meta";

/** The rule's metadata, in the order an organizer reads it: what it is, what it says, what it costs. */
export function AchievementDetailsCard({
  rule,
  totalUsers
}: Readonly<{ rule: AchievementRule; totalUsers: number }>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Details</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid grid-cols-3 gap-2">
          <div className="flex items-center gap-2">
            <CategoryIcon category={rule.category} />
            <div>
              <p className="text-muted-foreground text-xs">Category</p>
              <p className="capitalize">{rule.category}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ScopeIcon scope={rule.scope} />
            <div>
              <p className="text-muted-foreground text-xs">Scope</p>
              <p className="capitalize">{rule.scope}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <GrainIcon grain={rule.grain} />
            <div>
              <p className="text-muted-foreground text-xs">Grain</p>
              <p>{rule.grain.replace("_", " + ")}</p>
            </div>
          </div>
        </div>
        <Separator />
        <div>
          <p className="text-muted-foreground text-xs">Description (RU)</p>
          <p>{rule.description_ru}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Description (EN)</p>
          <p>{rule.description_en}</p>
        </div>
        <Separator />
        <div className="grid grid-cols-3 gap-2">
          <div className="flex items-center gap-2">
            <Hash className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-muted-foreground text-xs">Version</p>
              <p>{rule.rule_version}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Trophy className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-muted-foreground text-xs">Min Tournament</p>
              <p>{rule.min_tournament_id ?? "-"}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-muted-foreground" />
            <div>
              <p className="text-muted-foreground text-xs">Users Earned</p>
              <p className="font-medium">{totalUsers}</p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
