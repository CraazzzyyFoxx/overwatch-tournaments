"use client";

import { MoreLink } from "@/components/site/open-layout";
import Image from "@/components/ui/image";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export interface FeatureShot {
  key: string;
  title: string;
  text: string;
  /** A real production screenshot under `public/showcase/`. */
  img: string;
  alt: string;
  /** The docs article that sets the feature up. */
  docs: string;
}

/**
 * The organizer page's product tour: one screenshot window, one tab per
 * feature, the screenshot fading out from 75% down.
 *
 * Every panel stays mounted in one grid cell and shares the cell's two rows
 * through `subgrid`: the text row is as tall as the longest text, so the
 * window never moves between tabs, and the page under it never does either.
 * An inactive panel is `invisible`, which also takes it out of the tab order
 * and the accessibility tree.
 */
export function FeatureTabs({
  shots,
  labelledBy,
  docsLabel
}: Readonly<{ shots: readonly FeatureShot[]; labelledBy: string; docsLabel: string }>) {
  return (
    <Tabs defaultValue={shots[0]?.key}>
      <TabsList aria-labelledby={labelledBy}>
        {shots.map((shot) => (
          <TabsTrigger key={shot.key} value={shot.key}>
            {shot.title}
          </TabsTrigger>
        ))}
      </TabsList>
      <div className="mt-6 grid grid-rows-[auto_auto] gap-y-6">
        {shots.map((shot) => (
          <TabsContent
            key={shot.key}
            value={shot.key}
            forceMount
            className="col-start-1 row-span-2 row-start-1 mt-0 grid grid-rows-subgrid data-[state=inactive]:invisible"
          >
            <div className="max-w-[65ch] text-pretty text-ui leading-[1.6] text-[color:var(--aqt-fg-muted)]">
              <p>{shot.text}</p>
              <MoreLink href={shot.docs} className="mt-3">
                {docsLabel}
              </MoreLink>
            </div>
            <div className="aspect-[4/3] overflow-hidden rounded-xl bg-[color:var(--aqt-card)] [mask-image:linear-gradient(to_bottom,black_75%,transparent)] md:aspect-[16/10]">
              <Image
                src={`/showcase/${shot.img}`}
                width={1800}
                height={1250}
                sizes="(min-width: 1280px) 1280px, 100vw"
                alt={shot.alt}
                className="size-full object-cover object-left-top"
              />
            </div>
          </TabsContent>
        ))}
      </div>
    </Tabs>
  );
}
