import React from "react";
import { User } from "@/types/user.types";
import userService from "@/services/user.service";
import UserAchievementsFilter from "@/app/(site)/users/components/UserAchievementsFilter";
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

  const [achievements, profile] = await Promise.all([
    userService
      .getUserAchievements(user.id, {
        tournamentId,
        withoutTournament
      })
      .catch(() => [] as AchievementRarity[]),
    userService.getUserProfile(user.id)
  ]);

  return (
    <div className="aqt-player flex w-full flex-col gap-3.5">
      <UserAchievementsFilter tournaments={profile.tournaments} selectedValue={selectValue} />
      <AchievementsView achievements={achievements} />
    </div>
  );
};

export default UserAchievementPage;
