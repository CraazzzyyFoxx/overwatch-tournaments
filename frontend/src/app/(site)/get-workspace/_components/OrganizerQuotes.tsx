import { useTranslations } from "next-intl";

import { Section, SectionHead } from "@/components/site/open-layout";
import { WorkspaceAvatar, type WorkspaceAvatarSource } from "@/components/workspace/WorkspaceAvatar";

export interface OrganizerQuote {
  /** The organizer's own words: a snippet that fits in three lines, never a whole review. */
  text: string;
  author: string;
  /** What they do in their community, in the page's language: "организатор", "head admin". */
  role: string;
  community: WorkspaceAvatarSource;
}

const TITLE_ID = "gw-quotes-title";

/**
 * Organizers on the platform, in their own words.
 *
 * Built, not mounted: it belongs on `/get-workspace` right under the community
 * row (`CommunityProof`) once there are real quotes with real names, and it
 * renders nothing for an empty list until then. Never a placeholder quote.
 */
export function OrganizerQuotes({ quotes }: Readonly<{ quotes: readonly OrganizerQuote[] }>) {
  const t = useTranslations("getWorkspace.quotes");
  if (quotes.length === 0) return null;

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead title={t("title")} titleId={TITLE_ID} />
      <ul className="grid grid-cols-1 gap-x-8 gap-y-8 md:grid-cols-2 xl:grid-cols-3">
        {quotes.map((quote) => (
          <li
            key={`${quote.community.id}-${quote.author}`}
            className="min-w-0 border-t border-[color:var(--aqt-border-3)] pt-5"
          >
            <figure className="flex h-full flex-col gap-4">
              <blockquote className="text-pretty text-ui leading-[1.6] text-[color:var(--aqt-fg)]">
                {quote.text}
              </blockquote>
              <figcaption className="mt-auto flex min-w-0 items-center gap-3">
                <WorkspaceAvatar workspace={quote.community} size={32} />
                <span className="min-w-0">
                  <b className="block truncate font-semibold text-[color:var(--aqt-fg)]">
                    {quote.author}
                  </b>
                  <span className="block truncate text-caption text-[color:var(--aqt-fg-dim)]">
                    {quote.role}, {quote.community.name}
                  </span>
                </span>
              </figcaption>
            </figure>
          </li>
        ))}
      </ul>
    </Section>
  );
}
