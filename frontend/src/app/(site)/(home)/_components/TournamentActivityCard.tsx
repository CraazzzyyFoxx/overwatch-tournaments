import { getTranslations } from "next-intl/server";

import statisticsService from "@/services/statistics.service";

import { accentTint, getTenantMode } from "./home.helpers";
import { DashCardState, DashHeader } from "./dashboard-card-shell";

/** Players per tournament over the last 24 events, newest bar highlighted. */
export async function TournamentActivityCard() {
  const t = await getTranslations();
  const skipWorkspace = !(await getTenantMode());
  let visible = null;
  let max = 1;
  try {
    const data = await statisticsService.getTournaments({ skipWorkspace });
    visible = data.slice(-24);
    if (visible.length > 0) {
      max = Math.max(...visible.map((d) => d.players_count), 1);
    }
  } catch {
    // visible stays null on a genuine fetch error
  }

  const title = t("statistics.tournamentActivity");

  if (visible === null) {
    return <DashCardState title={title} state="error" />;
  }

  if (visible.length === 0) {
    return <DashCardState title={title} state="empty" />;
  }

  const labelEvery = Math.ceil(visible.length / 8);

  return (
    <>
      <DashHeader>{title}</DashHeader>
      <div className="px-5 pb-3 pt-5">
        <div className="flex items-end gap-[4px]" style={{ height: 110 }}>
          {visible.map((entry, i) => (
            <div
              key={entry.id}
              className="flex-1 flex flex-col justify-end"
              style={{ height: "100%" }}
            >
              <div
                style={{
                  height: `${(entry.players_count / max) * 100}%`,
                  background:
                    i === visible.length - 1
                      ? "var(--aqt-teal)"
                      : accentTint("var(--aqt-teal)", 22),
                  borderRadius: "3px 3px 0 0",
                  minHeight: 3
                }}
              />
            </div>
          ))}
        </div>
        <div className="flex mt-1.5">
          {visible.map((entry, i) => (
            <span
              key={entry.id}
              className="flex-1 text-center"
              style={{ fontSize: 11, color: "var(--aqt-fg-faint)" }}
            >
              {i % labelEvery === 0 ? entry.name : ""}
            </span>
          ))}
        </div>
      </div>
    </>
  );
}
