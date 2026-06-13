import React from "react";
import { User } from "@/types/user.types";
import userService from "@/services/user.service";
import { AchievementRarity } from "@/types/achievement.types";
import AchievementsView from "@/app/(site)/users/components/redesign/AchievementsView";

interface UserAchievementPageProps {
  user: User;
  selectedTournamentId?: string;
}

const parseAchievementFilter = (selectedTournamentId?: string) => {
  if (!selectedTournamentId || selectedTournamentId === "all") {
    return { tournamentId: undefined, withoutTournament: undefined, selectValue: "all" };
  }

  if (selectedTournamentId === "none") {
    return { tournamentId: undefined, withoutTournament: true, selectValue: "none" };
  }

  if (selectedTournamentId.startsWith("t-")) {
    const parsedTournamentId = Number(selectedTournamentId.slice(2));
    if (Number.isFinite(parsedTournamentId) && parsedTournamentId > 0) {
      return {
        tournamentId: parsedTournamentId,
        withoutTournament: undefined,
        selectValue: `t-${parsedTournamentId}`
      };
    }
  }

  return { tournamentId: undefined, withoutTournament: undefined, selectValue: "all" };
};

const UserAchievementPage = async ({ user, selectedTournamentId }: UserAchievementPageProps) => {
  const { tournamentId, withoutTournament, selectValue } = parseAchievementFilter(selectedTournamentId);

  let achievements: AchievementRarity[];
  let profile: Awaited<ReturnType<typeof userService.getUserProfile>>;
  try {
    [achievements, profile] = await Promise.all([
      userService
        .getUserAchievements(user.id, {
          tournamentId,
          withoutTournament,
          // Locked achievements only make sense for the global (all-tournaments) view.
          includeLocked: selectValue === "all"
        })
        .catch(() => [] as AchievementRarity[]),
      userService.getUserProfile(user.id)
    ]);
  } catch {
    return (
      <div className="aqt-player rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg)] px-6 py-10 text-center text-[13px] text-[color:var(--aqt-fg-muted)]">
        Could not load achievements. Please try again later.
      </div>
    );
  }

  return (
    <div className="aqt-player flex w-full flex-col gap-3.5">
      <AchievementsView
        achievements={achievements}
        tournaments={profile.tournaments}
        selectedTournamentValue={selectValue}
      />
    </div>
  );
};

export default UserAchievementPage;
