"use client";

import React, { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Achievement } from "@/types/achievement.types";
import { useInfiniteQuery } from "@tanstack/react-query";
import achievementsService from "@/services/achievements.service";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Card } from "@/components/ui/card";
import { useRouter } from "next/navigation";
import PlayerName from "@/components/PlayerName";

const AchievementUsers = ({ achievement }: { achievement: Achievement }) => {
  const t = useTranslations();
  const router = useRouter();

  const fetchUsers = async ({ pageParam = 1 }) => {
    return achievementsService.getUsers(achievement.id, pageParam, 30);
  };

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage
    // @ts-ignore
  } = useInfiniteQuery({
    queryKey: ["achievement", "users", achievement.id],
    queryFn: fetchUsers,
    getNextPageParam: (lastPage) =>
      lastPage.total / lastPage.per_page > lastPage.page ? lastPage.page + 1 : undefined
  });

  useEffect(() => {
    const handleScroll = () => {
      if (
        window.innerHeight + document.documentElement.scrollTop ===
        document.documentElement.offsetHeight
      ) {
        if (hasNextPage && !isFetchingNextPage) {
          fetchNextPage().then();
        }
      }
    };

    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  return (
    <div>
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("achievements.users.user")}</TableHead>
              <TableHead>{t("achievements.users.count")}</TableHead>
              {data?.pages[0].results[0].last_tournament && (
                <TableHead>{t("achievements.users.lastTournament")}</TableHead>
              )}
              {data?.pages[0].results[0].last_match && (
                <TableHead>{t("achievements.users.lastMatch")}</TableHead>
              )}
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.pages.map((group) =>
              group.results.map((achievement) => (
                <TableRow key={achievement.user.id}>
                  <TableCell>
                    <PlayerName player={achievement.user} includeSpecialization={false} />
                  </TableCell>
                  <TableCell>{achievement.count}</TableCell>
                  <TableCell
                    onClick={() =>
                      achievement.last_tournament
                        ? router.push(`/tournaments/${achievement.last_tournament.id}`)
                        : undefined
                    }
                  >
                    {achievement.last_tournament?.name}
                  </TableCell>
                  <TableCell
                    onClick={() =>
                      achievement.last_match
                        ? router.push(`/matches/${achievement.last_match.id}`)
                        : undefined
                    }
                  >
                    {achievement.last_match
                      ? `${achievement.last_match.home_team?.name ?? "?"} ${t("common.vs")} ${
                          achievement.last_match.away_team?.name ?? "?"
                        }`
                      : null}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </Card>
      <div className="flex justify-center mt-8">
        {hasNextPage && (
          <Button onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
            {t("common.loadMore")}
          </Button>
        )}
      </div>
    </div>
  );
};

export default AchievementUsers;
