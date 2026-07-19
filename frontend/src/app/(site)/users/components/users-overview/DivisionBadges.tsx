import React from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";

import { UserOverviewRow } from "@/types/user.types";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel } from "@/lib/division-grid";
import DivisionIcon from "@/components/DivisionIcon";

import { ROLE_LABEL_KEY } from "./utils";

const DivisionBadges = ({ user }: { user: UserOverviewRow }) => {
  const grid = useDivisionGrid();
  const t = useTranslations();

  if (user.roles.length === 0) {
    return <span className="text-xs text-muted-foreground">{t("users.list.division.noRoles")}</span>;
  }

  return (
    <div className="flex flex-wrap justify-center gap-2">
      {user.roles.map((role) => {
        const roleLabel = t(ROLE_LABEL_KEY[role.role]);
        const tierName =
          getDivisionLabel(grid, role.division) ?? t("common.divisionWithId", { id: String(role.division) });
        return (
          <div
            key={`${user.id}-${role.role}-${role.division}`}
            className="relative h-10 w-10"
            title={t("users.list.division.badgeTitle", { role: roleLabel, tier: tierName })}
          >
            <DivisionIcon
              division={role.division}
              width={40}
              height={40}
              className="h-10 w-10 rounded-full border border-border/60 bg-background/50 p-0.5 shadow-sm"
            />
            <div className="absolute -bottom-1 -right-1 rounded-full border border-border/60 bg-background/85 p-0.5">
              <Image
                src={`/roles/${role.role}.png`}
                alt={t("users.list.a11y.roleIconAlt", { role: roleLabel })}
                width={14}
                height={14}
                className="h-3.5 w-3.5"
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default React.memo(DivisionBadges);
