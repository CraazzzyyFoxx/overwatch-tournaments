import { getTranslations } from "next-intl/server";

import statisticsService from "@/services/statistics.service";

import { getTenantMode } from "./home.helpers";
import { DashCardState, DashHeader } from "./dashboard-card-shell";

/** Mean division per role across the season, as three proportional rings. */
export async function DivisionRingsCard() {
  const t = await getTranslations();
  const skipWorkspace = !(await getTenantMode());
  let roles: { label: string; val: number; pct: number; color: string }[] | null = null;
  try {
    const data = await statisticsService.getTournamentsDivision({ skipWorkspace });
    roles = [];
    if (data.length > 0) {
      const mean = (vals: (number | null)[]) => {
        const nums = vals.filter((v): v is number => v != null);
        return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
      };

      const meanTank = mean(data.map((d) => d.tank_avg_div));
      const meanDamage = mean(data.map((d) => d.damage_avg_div));
      const meanSupport = mean(data.map((d) => d.support_avg_div));
      const globalMax = Math.max(meanTank, meanDamage, meanSupport, 0.001);

      roles = [
        {
          label: t("statistics.roleTank"),
          val: meanTank,
          pct: (meanTank / globalMax) * 100,
          color: "var(--aqt-tank)"
        },
        {
          label: t("statistics.roleDamage"),
          val: meanDamage,
          pct: (meanDamage / globalMax) * 100,
          color: "var(--aqt-damage)"
        },
        {
          label: t("statistics.roleSupport"),
          val: meanSupport,
          pct: (meanSupport / globalMax) * 100,
          color: "var(--aqt-support)"
        }
      ];
    }
  } catch {
    // Fail silently
  }

  const title = t("statistics.avgDivisionByRole");

  if (roles === null) {
    return <DashCardState title={title} state="error" />;
  }

  if (roles.length === 0) {
    return <DashCardState title={title} state="empty" />;
  }

  const r = 28;
  const circum = 2 * Math.PI * r;

  return (
    <>
      <DashHeader>{title}</DashHeader>
      <div className="px-5 py-5 flex gap-4 items-start flex-wrap">
        {roles.map((role) => (
          <div
            key={role.label}
            className="flex flex-col items-center gap-2 flex-1"
            style={{ minWidth: 76 }}
          >
            <svg width="72" height="72" viewBox="0 0 72 72" aria-hidden>
              <circle cx="36" cy="36" r={r} fill="none" stroke="var(--aqt-border)" strokeWidth="7" />
              <circle
                cx="36"
                cy="36"
                r={r}
                fill="none"
                stroke={role.color}
                strokeWidth="7"
                strokeDasharray={`${(circum * role.pct) / 100} ${circum}`}
                strokeLinecap="round"
                transform="rotate(-90 36 36)"
              />
              <text
                x="36"
                y="40"
                textAnchor="middle"
                fontSize="12"
                fontWeight="700"
                fill={role.color}
                style={{ fontFamily: "var(--font-onest)" }}
              >
                {role.val.toFixed(1)}
              </text>
            </svg>
            <span className="text-label font-medium" style={{ color: "var(--aqt-fg-muted)" }}>
              {role.label}
            </span>
          </div>
        ))}
        <p
          className="flex-[2] text-label leading-relaxed self-center"
          style={{ color: "var(--aqt-fg-dim)", minWidth: 90 }}
        >
          {t("home.avgDivisionDesc")}
        </p>
      </div>
    </>
  );
}
