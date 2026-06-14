import { ImageResponse } from "next/og";
import userService from "@/services/user.service";
import { decodePlayerSlug, getPlayerImage } from "@/utils/player";
import { SITE_NAME, SITE_URL_OBJ } from "@/config/site";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = `${SITE_NAME} player profile`;

const toAbsolute = (value: string) =>
  value.startsWith("http") ? value : new URL(value, SITE_URL_OBJ).toString();

// Open Graph / Twitter card image, generated per player. Falls back to a plain
// branded card if the player can't be loaded or the avatar fails to render.
export default async function Image({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;

  let name = "Player";
  let descriptor = "";
  let winrate = "—";
  let tournaments = 0;
  let avatar: string | null = null;

  try {
    const user = await userService.getUserByName(decodePlayerSlug(slug));
    const profile = await userService.getUserProfile(user.id);
    name = user.name;
    const primaryRole = profile.roles.length
      ? profile.roles.reduce((best, current) => (current.tournaments > best.tournaments ? current : best))
      : null;
    descriptor = primaryRole ? `${primaryRole.role} · Division ${primaryRole.division}` : "";
    tournaments = profile.tournaments_count ?? 0;
    if (profile.maps_total > 0) {
      winrate = `${((profile.maps_won / profile.maps_total) * 100).toFixed(0)}% WR`;
    }
    avatar = toAbsolute(getPlayerImage(profile, user));
  } catch {
    // keep defaults — render a generic branded card
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "linear-gradient(135deg, #0b1120 0%, #111a2e 100%)",
          color: "#e8eef7",
          padding: "64px 72px",
          fontFamily: "sans-serif"
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 40 }}>
          {avatar ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={avatar}
              alt=""
              width={220}
              height={220}
              style={{ borderRadius: 24, objectFit: "cover", border: "4px solid #1f2b45" }}
            />
          ) : null}
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{ fontSize: 76, fontWeight: 800, lineHeight: 1.05 }}>{name}</div>
            {descriptor ? <div style={{ fontSize: 34, color: "#8aa0bd" }}>{descriptor}</div> : null}
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", gap: 48 }}>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: 48, fontWeight: 700, color: "#2dd4bf" }}>{winrate}</span>
              <span style={{ fontSize: 26, color: "#6b7f9c" }}>map winrate</span>
            </div>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <span style={{ fontSize: 48, fontWeight: 700 }}>{tournaments}</span>
              <span style={{ fontSize: 26, color: "#6b7f9c" }}>tournaments</span>
            </div>
          </div>
          <div style={{ fontSize: 30, fontWeight: 700, color: "#8aa0bd" }}>{SITE_NAME}</div>
        </div>
      </div>
    ),
    { ...size }
  );
}
