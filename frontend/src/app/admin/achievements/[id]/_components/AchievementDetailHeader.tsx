"use client";

import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle,
  CircleOff,
  Eye,
  EyeOff,
  Pencil,
  Play,
  TestTube,
  Trash2
} from "lucide-react";

import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { Button } from "@/components/ui/button";
import type { AchievementRule } from "@/types/admin.types";

export function AchievementDetailHeader({
  rule,
  canUpdate,
  canDelete,
  isEvaluating,
  onTest,
  onEvaluate,
  onToggle,
  onEdit,
  onDelete
}: Readonly<{
  rule: AchievementRule;
  canUpdate: boolean;
  canDelete: boolean;
  isEvaluating: boolean;
  onTest: () => void;
  onEvaluate: () => void;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}>) {
  return (
    <div className="flex items-start gap-3">
      <Button variant="ghost" size="icon" asChild aria-label="Back to achievements">
        <Link href="/admin/achievements">
          <ArrowLeft aria-hidden className="h-4 w-4" />
        </Link>
      </Button>
      {rule.image_url && (
        <img
          src={rule.image_url}
          alt={rule.name}
          className="h-12 w-12 rounded-lg object-cover border"
        />
      )}
      <div className="min-w-0 flex-1">
        <AdminPageHeader
          title={rule.name}
          description={rule.slug}
          meta={
            rule.enabled ? (
              <StatusIcon icon={CheckCircle} label="Enabled" variant="success" />
            ) : (
              <StatusIcon icon={CircleOff} label="Disabled" variant="muted" />
            )
          }
          actions={
            <>
              <Button variant="outline" size="sm" onClick={onTest}>
                <TestTube aria-hidden className="mr-2 h-4 w-4" />
                Test conditions
              </Button>
              <Button variant="outline" size="sm" onClick={onEvaluate}>
                <Play
                  aria-hidden
                  className={`mr-2 h-4 w-4 ${isEvaluating ? "animate-spin" : ""}`}
                />
                {isEvaluating ? "Evaluating…" : "Run evaluation"}
              </Button>
              {canUpdate && (
                <Button variant="outline" size="sm" onClick={onToggle}>
                  {rule.enabled ? (
                    <EyeOff aria-hidden className="mr-2 h-4 w-4" />
                  ) : (
                    <Eye aria-hidden className="mr-2 h-4 w-4" />
                  )}
                  {rule.enabled ? "Disable achievement" : "Enable achievement"}
                </Button>
              )}
              {canUpdate && (
                <Button size="sm" onClick={onEdit}>
                  <Pencil aria-hidden className="mr-2 h-4 w-4" />
                  Edit achievement
                </Button>
              )}
              {canDelete && (
                <Button variant="destructive" size="sm" onClick={onDelete}>
                  <Trash2 aria-hidden className="mr-2 h-4 w-4" />
                  Delete achievement
                </Button>
              )}
            </>
          }
        />
      </div>
    </div>
  );
}
