"use client";

import { Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { AchievementOverrideRead, AchievementRule } from "@/types/admin.types";

/**
 * Every manual grant and revoke in the workspace. Rule ids are resolved to
 * slugs through the catalog when it has loaded, and fall back to the raw id
 * rather than rendering a blank cell.
 */
export function AchievementOverridesCard({
  overrides,
  rules,
  onDelete,
  isDeleting,
}: Readonly<{
  overrides: AchievementOverrideRead[];
  rules?: AchievementRule[];
  onDelete: (id: number) => void;
  isDeleting: boolean;
}>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle asChild>
          <h2>Manual overrides</h2>
        </CardTitle>
        <CardDescription>
          Achievements granted or revoked by hand, outside the evaluation engine.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Achievement</TableHead>
              <TableHead>User</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>Tournament</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {overrides.map((ov) => (
              <TableRow key={ov.id}>
                <TableCell>
                  {rules?.find((r) => r.id === ov.achievement_rule_id)?.slug ?? ov.achievement_rule_id}
                </TableCell>
                <TableCell className="tabular-nums">#{ov.user_id}</TableCell>
                <TableCell>
                  <Badge variant={ov.action === "grant" ? "success" : "destructive"}>
                    {ov.action}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-48 truncate">{ov.reason}</TableCell>
                <TableCell className="tabular-nums">{ov.tournament_id ?? "—"}</TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={() => onDelete(ov.id)}
                    disabled={isDeleting}
                    aria-label={`Remove the ${ov.action} override on ${
                      rules?.find((r) => r.id === ov.achievement_rule_id)?.name ??
                      `achievement #${ov.achievement_rule_id}`
                    } for user #${ov.user_id}`}
                  >
                    <Trash2 className="h-4 w-4 text-destructive" aria-hidden />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
