"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { roleImageSrc } from "@/lib/roster/player-role";
import { ROLE_LABEL_KEY } from "@/app/(site)/users/components/shared/list-utils";
import type { UserRoleType } from "@/types/user.types";
import type { DivisionGridVersion } from "@/types/workspace.types";

import styles from "./Users.module.css";

/**
 * A player's division badge for one role, titled with the tier name from the
 * grid the number actually belongs to — `roleGrid` in all-workspaces mode
 * (each row's own tournament grid), the workspace's own grid otherwise.
 */
export const DivisionHex = ({
  role,
  division,
  roleGrid,
  size = 36
}: Readonly<{
  role: UserRoleType;
  division: number;
  roleGrid?: DivisionGridVersion | null;
  size?: number;
}>) => {
  const t = useTranslations();
  const workspaceGrid = useDivisionGrid();
  const title = t("users.list.division.badgeTitle", {
    role: t(ROLE_LABEL_KEY[role]),
    tier:
      getDivisionLabel(roleGrid ?? workspaceGrid, division) ??
      t("common.divisionWithId", { id: String(division) })
  });

  return (
    <div
      className={styles.divisionBadge}
      title={title}
      style={{ width: size + 2, height: size + 2 }}
    >
      <DivisionIcon
        division={division}
        tournamentGrid={roleGrid}
        width={size}
        height={size}
        className="h-full w-full"
      />
      <div className={styles.divisionRoleDot}>
        <Image
          src={roleImageSrc(role)}
          alt={t("users.list.a11y.roleAlt", { role: t(ROLE_LABEL_KEY[role]) })}
          width={12}
          height={12}
        />
      </div>
    </div>
  );
};
