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
  TableRow
} from "@/components/ui/table";
import { useFormatter } from "@/lib/datetime/client";
import type { AchievementOverrideRead } from "@/types/admin.types";

/** The manual grants and revocations recorded against this one rule. */
export function RuleOverridesCard({
  overrides,
  onDelete
}: Readonly<{
  overrides: AchievementOverrideRead[];
  onDelete: (id: number) => void;
}>) {
  const format = useFormatter();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Overrides</CardTitle>
        <CardDescription>Manual grants and revocations</CardDescription>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User ID</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>Reason</TableHead>
              <TableHead>Tournament</TableHead>
              <TableHead>Date</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {overrides.map((ov) => (
              <TableRow key={ov.id}>
                <TableCell>#{ov.user_id}</TableCell>
                <TableCell>
                  <Badge variant={ov.action === "grant" ? "success" : "destructive"}>
                    {ov.action}
                  </Badge>
                </TableCell>
                <TableCell className="max-w-48 truncate">{ov.reason}</TableCell>
                <TableCell>{ov.tournament_id ?? "-"}</TableCell>
                <TableCell className="text-muted-foreground">
                  {format.dateTime(new Date(ov.created_at), { dateStyle: "medium" })}
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${ov.action} override`}
                    onClick={() => onDelete(ov.id)}
                  >
                    <Trash2 aria-hidden className="h-4 w-4 text-destructive" />
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
