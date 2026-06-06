"use client";

import React, { useCallback } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { MapPin } from "lucide-react";
import { TypographyH4 } from "@/components/ui/typography";
import { UserMapRead } from "@/types/user.types";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

export interface UserTopMapsCardProps {
  maps: UserMapRead[];
  className?: string;
}

const UserTopMapsCard = ({ maps, className }: UserTopMapsCardProps) => {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const navToTab = useCallback(
    (tab: string) => {
      const newSearchParams = new URLSearchParams(searchParams || undefined);
      newSearchParams.set("tab", tab);
      router.push(`${pathname}?${newSearchParams.toString()}`);
    },
    [searchParams, pathname, router]
  );

  return (
    <Card className={className}>
      <CardHeader>
        <div className="flex flex-row gap-2 items-center align-text-top">
          <MapPin />
          <TypographyH4>Top Maps</TypographyH4>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {maps.slice(0, 5).map((map, index) => (
          <div key={index} className="flex flex-row gap-2">
            <div className="overflow-hidden relative max-h-[55px] max-w-[300px] border-b-[1px] border-border">
              <Image
                className="brightness-50"
                src={map.map.image_path}
                alt="Map"
                height={150}
                width={300}
              />
              <h4 className="absolute bottom-0 left-0 m-2 text-xl p-1 font-semibold">
                {map.map.name}
              </h4>
              <div className="absolute bottom-0 right-0 m-2 text-sm">
                <TypographyH4>{(map.win_rate * 100).toFixed(0)}%</TypographyH4>
                <p className="text-xs text-muted-foreground text-right font-semibold">
                  {map.win}W-{map.loss}L
                </p>
              </div>
            </div>
          </div>
        ))}
        <div className="flex items-center justify-center py-4">
          <Button variant="secondary" className="min-w-[160px]" onClick={() => navToTab("maps")}>
            View all Maps
          </Button>
        </div>
      </CardContent>
    </Card>
  );
};

export default UserTopMapsCard;
