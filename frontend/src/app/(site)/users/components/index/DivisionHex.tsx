"use client";

import Image from "next/image";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { roleImageSrc } from "@/lib/roster/player-role";
import { ROLE_LABEL_KEY } from "@/app/(site)/users/components/shared/list-utils";
import type { UserRoleType } from "@/types/user.types";

import styles from "./Users.module.css";

/** A player's division badge for one role, titled with the workspace's own tier name. */
export const DivisionHex = ({
  role,
  division,
  size = 36
}: Readonly<{
  role: UserRoleType;
  division: number;
  size?: number;
}>) => {
  const t = useTranslations();
  const divisionGrid = useDivisionGrid();
  const title = t("users.list.division.badgeTitle", {
    role: t(ROLE_LABEL_KEY[role]),
    tier:
      getDivisionLabel(divisionGrid, division) ??
      t("common.divisionWithId", { id: String(division) })
  });

  return (
    <div
      className={styles.divisionBadge}
      title={title}
      style={{ width: size + 2, height: size + 2 }}
    >
      <DivisionIcon division={division} width={size} height={size} className="h-full w-full" />
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
