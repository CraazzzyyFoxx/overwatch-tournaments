"use client";

import React, { useTransition } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";

type OwalSeasonFilterProps = {
  seasons: string[];
  selectedSeason: string;
};

const OwalSeasonFilter = ({ seasons, selectedSeason }: OwalSeasonFilterProps) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const onValueChange = (value: string) => {
    const nextSearchParams = new URLSearchParams(searchParams.toString());
    nextSearchParams.set("season", value);

    startTransition(() => {
      router.push(`${pathname}?${nextSearchParams.toString()}`);
    });
  };

  return (
    <div className="flex items-center gap-3">
      <span className="text-sm text-muted-foreground">Season:</span>
      <Select value={selectedSeason} onValueChange={onValueChange}>
        <SelectTrigger className="w-full sm:w-[260px]">
          <SelectValue placeholder="Select season" />
        </SelectTrigger>
        <SelectContent>
          {seasons.map((season) => (
            <SelectItem key={season} value={season}>
              {season}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

export default OwalSeasonFilter;
