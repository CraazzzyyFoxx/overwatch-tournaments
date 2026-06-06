"use client";

import React, { useMemo } from "react";
import {
  ChartConfig,
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent
} from "@/components/ui/chart";
import { Bar, BarChart, XAxis, YAxis } from "recharts";
import { HeroPlaytime } from "@/types/hero.types";

export interface HeroPlaytimeChartProps {
  heroes: HeroPlaytime[];
  /** Height per hero row (px). Default: 40 */
  rowHeight?: number;
  /** Minimum chart height (px). Default: 240 */
  minHeight?: number;
  /** Bar thickness (px). Default: 32 */
  barSize?: number;
  /** Icon size (px). Defaults based on barSize */
  iconSize?: number;
}

// @ts-ignore
const CustomYAxisTick = ({ x, y, payload, icons, iconSize }) => {
  return (
    <g transform={`translate(${x},${y})`}>
      <image
        href={icons.get(payload.value)}
        x={-Math.round(iconSize * 0.67)}
        y={-Math.round(iconSize / 2)}
        height={iconSize}
        width={iconSize}
      />
    </g>
  );
};

const HeroPlaytimeChart = ({
  heroes,
  rowHeight: rowHeightProp,
  minHeight: minHeightProp,
  barSize: barSizeProp,
  iconSize: iconSizeProp
}: HeroPlaytimeChartProps) => {
  const displayHeroes = useMemo(() => {
    return [...heroes]
      .sort((a, b) => b.playtime - a.playtime)
  }, [heroes]);

  const chartData = useMemo(() => {
    return displayHeroes.map((heroPlaytime) => {
      return {
        name: heroPlaytime.hero.slug,
        value: heroPlaytime.playtime * 100,
        fill: `var(--color-${heroPlaytime.hero.slug})`,
        icon: heroPlaytime.hero.image_path
      };
    });
  }, [displayHeroes]);

  const heroesIcons: Map<string, string> = useMemo(() => {
    const icons = new Map<string, string>();
    displayHeroes.forEach((heroPlaytime) => {
      icons.set(heroPlaytime.hero.slug, heroPlaytime.hero.image_path);
    });
    return icons;
  }, [displayHeroes]);

  const rowHeight = rowHeightProp ?? 40;
  const minHeight = minHeightProp ?? 240;
  const barSize = barSizeProp ?? 32;
  const iconSize = iconSizeProp ?? (barSize >= 28 ? 30 : 24);

  const chartConfig: ChartConfig = useMemo(() => {
    const charData = {
      value: {
        label: "Percentage of play time on the hero"
      }
    };
    displayHeroes.forEach((heroPlaytime) => {
      // @ts-ignore
      charData[heroPlaytime.hero.slug] = {
        label: heroPlaytime.hero.name,
        color: heroPlaytime.hero.color
      };
    });
    return charData;
  }, [displayHeroes]);

  const chartHeight = Math.max(displayHeroes.length * rowHeight, minHeight);

  return (
    <ChartContainer
      config={chartConfig}
      className="w-full aspect-auto"
      style={{ height: chartHeight }}
    >
      <BarChart
        accessibilityLayer
        data={chartData}
        layout="vertical"
        margin={{
          left: 0
        }}
      >
        <YAxis
          dataKey="name"
          type="category"
          tickLine={false}
          tickMargin={10}
          axisLine={false}
          // @ts-ignore
          tick={<CustomYAxisTick icons={heroesIcons} iconSize={iconSize} />}
        />
        <XAxis dataKey="value" type="number" hide />
        <ChartTooltip content={<ChartTooltipContent className="w-62.5" indicator="dot" />} />
        <Bar dataKey="value" layout="vertical" radius={5} barSize={barSize} />
      </BarChart>
    </ChartContainer>
  );
};

export default HeroPlaytimeChart;
