import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export default function Loading() {
  return (
    <div className="flex flex-col gap-8">
      <div>
        <Skeleton className="h-10 w-[200px]" />
      </div>
      <Card>
        <CardContent className="flex flex-row gap-8 p-4">
          <div className="flex flex-row gap-4 items-center">
            <Skeleton className="h-10 w-10 rounded-full" />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-6 w-32" />
            </div>
            <div className="flex flex-col gap-2">
              <Skeleton className="h-4 w-24" />
              <Skeleton className="h-6 w-32" />
            </div>
          </div>
        </CardContent>
      </Card>
      <div className="py-8 grid xs:grid-cols-1 xl:grid-cols-3 gap-8">
        <Card>
          <CardHeader className="px-0 pl-4">
            <Skeleton className="h-8 w-48 mb-2" />
            <Skeleton className="h-5 w-32" />
          </CardHeader>
          <div className="p-4 space-y-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        </Card>
        <Card>
          <CardHeader>
            <div className="flex gap-4">
              <div className="flex-1 flex flex-col items-end gap-2">
                <Skeleton className="h-8 w-24" />
                <Skeleton className="h-6 w-12" />
              </div>
              <div className="flex items-end">
                <Skeleton className="h-6 w-4" />
              </div>
              <div className="flex-1 flex flex-col items-start gap-2">
                <Skeleton className="h-8 w-24" />
                <Skeleton className="h-6 w-12" />
              </div>
            </div>
          </CardHeader>
          <CardContent className="grid xs:grid-cols-1 xs1:grid-cols-2 md:grid-cols-3 xl:grid-cols-2 gap-4">
            <Skeleton className="h-[115px] w-full" />
            <Skeleton className="h-[115px] w-full" />
            <Skeleton className="h-[115px] w-full" />
            <Skeleton className="h-[115px] w-full" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="px-0 pl-4">
            <Skeleton className="h-8 w-48 mb-2" />
            <Skeleton className="h-5 w-32" />
          </CardHeader>
          <div className="p-4 space-y-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        </Card>
      </div>
    </div>
  );
}
