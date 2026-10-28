import type { ComponentProps } from "react";
import NextImage, { type ImageProps } from "next/image";

// The list `next.config.mjs` hands to `images.remotePatterns`; both read it at build time. As there, each entry is a
// URL, so it fixes protocol, host and port, its empty query admits only a src without one, and its path is a glob
// (`**` spans segments, `*` stays inside one).
const REMOTE = (process.env.NEXT_PUBLIC_IMAGE_REMOTE_PATTERNS ?? "")
  .split(",")
  .map((pattern) => pattern.trim())
  .filter(Boolean)
  .map((pattern) => new URL(pattern))
  .map((url) => ({
    origin: url.origin,
    path: new RegExp(
      `^${url.pathname
        .replace(/[.+?^${}()|[\]\\]/g, "\\$&")
        .replace(/\*\*/g, "\u0000")
        .replace(/\*/g, "[^/]*")
        .replace(/\u0000/g, ".*")}$`
    )
  }));

function isOptimizable(src: ImageProps["src"]): boolean {
  if (typeof src !== "string") return true;
  if (src.startsWith("/") && !src.startsWith("//")) return true;
  try {
    const url = new URL(src);
    return (
      url.search === "" &&
      REMOTE.some((pattern) => pattern.origin === url.origin && pattern.path.test(url.pathname))
    );
  } catch {
    return false;
  }
}

/**
 * `next/image` that sends only the configured hosts through the optimizer. Stored image URLs are not all on them: an
 * admin may paste any URL into the catalog or a division grid, and another deployment keeps another bucket. The
 * optimizer refuses such a URL (`next dev` throws while rendering, a build serves a 400), so it is served as is.
 */
export default function Image(props: ComponentProps<typeof NextImage>) {
  return (
    <NextImage
      {...props}
      {...(!props.unoptimized && !isOptimizable(props.src) ? { unoptimized: true } : null)}
    />
  );
}
