"use client";

import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { SettingGroup } from "@/components/kit/SettingRow";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@craazzzyyfoxx/admin-kit/ui/table";
import { TONE_TEXT } from "@craazzzyyfoxx/admin-kit/ui/tone";
import { useFormatter } from "@/lib/datetime/client";
import type { AchievementOverrideRead, AchievementRule } from "@/types/admin.types";
import type { Tournament } from "@/types/tournament.types";

/**
 * Manual grants and revokes. The list page passes `rules` and gets an
 * achievement column (rule ids resolved to slugs once the catalog has loaded);
 * a rule's own page omits it, every row there is that rule.
 */
export function AchievementOverridesCard({
  overrides,
  rules,
  tournaments,
  onDelete,
  isDeleting = false,
}: Readonly<{
  overrides: AchievementOverrideRead[];
  rules?: AchievementRule[];
  tournaments: Tournament[];
  onDelete: (id: number) => void;
  isDeleting?: boolean;
}>) {
  const t = useTranslations("adminAchievements");
  const format = useFormatter();
  return (
    <SettingGroup id="overrides" title={t("overrides.title")}>
      <Table>
        <TableHeader>
          <TableRow>
            {rules && <TableHead>{t("common.achievement")}</TableHead>}
            <TableHead>{t("common.user")}</TableHead>
            <TableHead>{t("common.action")}</TableHead>
            <TableHead>{t("common.reason")}</TableHead>
            <TableHead>{t("common.tournament")}</TableHead>
            <TableHead>{t("common.date")}</TableHead>
            <TableHead className="w-12" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {overrides.map((ov) => (
            <TableRow key={ov.id}>
              {rules && (
                <TableCell>
                  {rules.find((r) => r.id === ov.achievement_rule_id)?.slug ?? ov.achievement_rule_id}
                </TableCell>
              )}
              <TableCell className="tabular-nums">{t("overrides.user", { id: ov.user_id })}</TableCell>
              <TableCell className={ov.action === "grant" ? TONE_TEXT.success : TONE_TEXT.danger}>
                {ov.action === "grant" ? t("common.grant") : t("common.revoke")}
              </TableCell>
              <TableCell className="max-w-48 truncate">{ov.reason}</TableCell>
              <TableCell>
                {ov.tournament_id != null &&
                  (tournaments.find((tournament) => tournament.id === ov.tournament_id)?.name ??
                    t("common.tournamentId", { id: ov.tournament_id }))}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {format.dateTime(new Date(ov.created_at), { dateStyle: "medium" })}
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => onDelete(ov.id)}
                  disabled={isDeleting}
                  aria-label={t("overrides.removeLabel", { userId: ov.user_id })}
                  title={t("overrides.removeLabel", { userId: ov.user_id })}
                >
                  <Trash2 className="h-4 w-4 text-destructive" aria-hidden />
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </SettingGroup>
  );
}
