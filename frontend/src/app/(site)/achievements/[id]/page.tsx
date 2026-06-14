import React from "react";
import Image from "next/image";
import achievementsService from "@/services/achievements.service";
import AchievementUsers from "@/app/(site)/achievements/[id]/components/AchiementUsers";

export const dynamic = 'force-dynamic';

const AchievementPage = async (props: { params: Promise<{ id: number }> }) => {
  const params = await props.params;
  const data = await achievementsService.getOne(params.id);

  return (
    <div>
      <div className="lg:ml-5 flex flex-row gap-4 items-center mb-8">
        <Image
          className="rounded-xl"
          src={data.image_url ?? `/achievements/${data.slug}.webp`}
          width={100}
          height={100}
          alt={data.slug}
        />
        <div className="flex flex-col">
          <h3 className="scroll-m-20 xs:text-lg xs1:text-2xl font-semibold tracking-tight">
            {data.name}
          </h3>
          <div className="flex gap-2">
            <p className="text-muted-foreground text-sm">{data.description_ru}</p>
          </div>
        </div>
      </div>
      <AchievementUsers achievement={data} />
    </div>
  );
};

export default AchievementPage;
