import React from "react";
import type { User, UserProfile } from "@/types/user.types";
import { getPlayerImage } from "@/utils/player";
import { SITE_NAME, SITE_URL_OBJ } from "@/config/site";

const toAbsolute = (value: string) =>
  value.startsWith("http") ? value : new URL(value, SITE_URL_OBJ).toString();

/**
 * Structured data for a player profile: ProfilePage + Person (mainEntity) +
 * BreadcrumbList. Rendered server-side into the initial HTML so crawlers and
 * rich results can index the profile. `url` must be the canonical profile URL.
 */
export const ProfileJsonLd = ({ user, profile, url }: { user: User; profile: UserProfile; url: string }) => {
  const primaryRole = profile.roles.length
    ? profile.roles.reduce((best, current) => (current.tournaments > best.tournaments ? current : best))
    : null;

  const image = toAbsolute(getPlayerImage(profile, user));
  const descriptor = primaryRole ? `${primaryRole.role} · Division ${primaryRole.division}` : "Player";
  const description = `${user.name} — ${descriptor} · ${profile.tournaments_count ?? 0} tournaments on ${SITE_NAME}.`;
  const personId = `${url}#person`;

  const data = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "ProfilePage",
        "@id": url,
        url,
        name: `${user.name} — Player Profile`,
        mainEntity: { "@id": personId }
      },
      {
        "@type": "Person",
        "@id": personId,
        name: user.name,
        url,
        image,
        description
      },
      {
        "@type": "BreadcrumbList",
        itemListElement: [
          { "@type": "ListItem", position: 1, name: "Home", item: SITE_URL_OBJ.toString() },
          { "@type": "ListItem", position: 2, name: "Players", item: new URL("/users", SITE_URL_OBJ).toString() },
          { "@type": "ListItem", position: 3, name: user.name, item: url }
        ]
      }
    ]
  };

  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }} />;
};
