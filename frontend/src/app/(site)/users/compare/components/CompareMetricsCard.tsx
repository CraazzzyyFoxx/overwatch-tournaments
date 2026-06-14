"use client";

import Image from "next/image";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { CompareRow } from "@/app/(site)/users/compare/types";
import { formatDuration, formatMetricValue, formatPercent, getGlowVarsFromColor } from "@/app/(site)/users/compare/utils";
import GlassGlow from "@/app/(site)/users/compare/components/GlassGlow";
import TrendDelta from "@/app/(site)/users/compare/components/TrendDelta";

interface CompareMetricsCardProps {
  mode: "subject" | "baseline";
  title: string;
  description: string;
  rows: CompareRow[];
  loading: boolean;
  errorMessage?: string;
  isHeroScope: boolean;
  heroName?: string;
  heroImagePath?: string;
  heroDominantColor?: string | null;
  playtimeSeconds?: number;
  playtimeLabel?: string;
}

const CompareMetricsSkeleton = ({ mode, isHeroScope }: { mode: "subject" | "baseline"; isHeroScope: boolean }) => {
  const rowCount = isHeroScope ? 6 : 8;

  return (
    <div className="rounded-xl border bg-background/10 p-1">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Metric</TableHead>
            {mode === "subject" ? <TableHead className="text-right">Value</TableHead> : null}
            {mode === "subject" && !isHeroScope ? <TableHead className="text-right">Percentile</TableHead> : null}
            {mode === "baseline" ? <TableHead className="text-right">Baseline</TableHead> : null}
            {mode === "baseline" ? <TableHead className="text-right">Delta</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {Array.from({ length: rowCount }).map((_, index) => (
            <TableRow key={`skeleton-${mode}-${index}`} className="h-12">
              <TableCell className="align-middle">
                <Skeleton className="h-4 w-38" />
              </TableCell>
              <TableCell className="align-middle">
                <div className="flex justify-end">
                  <Skeleton className="h-4 w-16" />
                </div>
              </TableCell>
              {mode === "subject" && !isHeroScope ? (
                <TableCell className="align-middle">
                  <div className="flex justify-end">
                    <Skeleton className="h-4 w-14" />
                  </div>
                </TableCell>
              ) : null}
              {mode === "baseline" ? (
                <TableCell className="align-middle">
                  <div className="flex justify-end">
                    <Skeleton className="h-4 w-20" />
                  </div>
                </TableCell>
              ) : null}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
};

const CompareMetricsCard = ({
  mode,
  title,
  description,
  rows,
  loading,
  errorMessage,
  isHeroScope,
  heroName,
  heroImagePath,
  heroDominantColor,
  playtimeSeconds,
  playtimeLabel = "Playtime"
}: CompareMetricsCardProps) => {
  const heroGlowVars = isHeroScope ? getGlowVarsFromColor(heroDominantColor) : null;

  return (
    <Card className="relative overflow-hidden min-h-125" style={heroGlowVars ? (heroGlowVars as React.CSSProperties) : undefined}>
      <GlassGlow />

      {isHeroScope && heroImagePath ? (
        <div className="absolute top-5 right-5 z-20 rounded-lg p-1 shadow-lg">
          <Image
            src={heroImagePath}
            alt={heroName ?? "Hero"}
            width={64}
            height={64}
            className="h-16 w-16 rounded-md object-cover"
          />
        </div>
      ) : null}

      <CardHeader className={`relative pb-3`}>
        <CardTitle className="text-lg">{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
        {isHeroScope ? (
          <div className="flex flex-wrap items-center gap-2 pt-2 text-xs text-muted-foreground">
            <span>Hero: {heroName ?? "All heroes"}</span>
            <span>•</span>
            <span>
              {playtimeLabel}: {formatDuration(playtimeSeconds ?? 0)}
            </span>
          </div>
        ) : null}
      </CardHeader>

      <CardContent className="relative">
        {loading ? (
          <CompareMetricsSkeleton mode={mode} isHeroScope={isHeroScope} />
        ) : errorMessage ? (
          <p className="text-sm text-destructive">{errorMessage}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-muted-foreground">No metrics available for current filters.</p>
        ) : (
          <div className="rounded-xl border bg-background/10 p-1">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Metric</TableHead>
                  {mode === "subject" ? <TableHead className="text-right">Value</TableHead> : null}
                  {mode === "subject" && !isHeroScope ? <TableHead className="text-right">Percentile</TableHead> : null}
                  {mode === "baseline" ? <TableHead className="text-right">Baseline</TableHead> : null}
                  {mode === "baseline" ? <TableHead className="text-right">Delta</TableHead> : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={`${mode}-${row.key}`} className="h-12">
                    <TableCell className="font-medium align-middle leading-none">{row.label}</TableCell>

                    {mode === "subject" ? (
                      <TableCell className="text-right tabular-nums align-middle whitespace-nowrap leading-none">
                        {formatMetricValue(row.subjectValue)}
                      </TableCell>
                    ) : null}

                    {mode === "subject" && !isHeroScope ? (
                      <TableCell className="text-right tabular-nums align-middle whitespace-nowrap leading-none">
                        {formatPercent(row.percentile)}
                      </TableCell>
                    ) : null}

                    {mode === "baseline" ? (
                      <TableCell className="text-right tabular-nums align-middle whitespace-nowrap leading-none">
                        {formatMetricValue(row.baselineValue)}
                      </TableCell>
                    ) : null}

                    {mode === "baseline" ? (
                      <TableCell className="text-right align-middle whitespace-nowrap leading-none">
                        <TrendDelta
                          delta={row.delta}
                          deltaPercent={row.deltaPercent}
                          betterWorse={row.betterWorse}
                        />
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default CompareMetricsCard;
