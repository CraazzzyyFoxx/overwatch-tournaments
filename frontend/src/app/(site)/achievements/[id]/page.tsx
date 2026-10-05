
import achievementsService from "@/services/achievements.service";
import { cn } from "@/lib/utils";
import { resolveStatsScope } from "@/lib/site/tenant-host";
import { classifyRarity, rarityVarClass } from "@/app/(site)/users/components/achievements/rarity";
import AchievementUsers from "@/app/(site)/achievements/[id]/components/AchievementUsers";
import AchievementDetailHeader from "@/app/(site)/achievements/[id]/components/AchievementDetailHeader";
import AchievementConditionsCard from "@/app/(site)/achievements/[id]/components/AchievementConditionsCard";

export const dynamic = "force-dynamic";

const AchievementPage = async (props: { params: Promise<{ id: number }> }) => {
  const params = await props.params;
  // In the all-workspaces scope the catalogue links one copy per slug with the
  // slug's pooled numbers; the detail asks for the same pooling.
  const scope = await resolveStatsScope();
  const data = await achievementsService.getOne(params.id, scope);
  const rarity = classifyRarity(data.rarity * 100);

  return (
    <div className={cn("aqt-player space-y-6", rarityVarClass(rarity))}>
      <AchievementDetailHeader achievement={data} />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]">
        <AchievementConditionsCard achievement={data} />
        <AchievementUsers achievement={data} scope={scope} />
      </div>
    </div>
  );
};

export default AchievementPage;
