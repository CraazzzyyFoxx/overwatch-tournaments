import React from "react";

import { Card, CardHeader } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-5 rounded-md" />
          <Skeleton className="h-6 w-56" />
        </div>
      </CardHeader>
      <div className="px-2 pb-4">
        <Skeleton className="h-[520px] w-full rounded-xl" />
      </div>
    </Card>
  );
}
