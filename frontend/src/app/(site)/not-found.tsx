import { NotFoundView } from "@/components/NotFoundView";

/**
 * Catches `notFound()` thrown by a (site) page — a missing player, tournament
 * or match. Without it the nearest boundary is the root one, which renders
 * outside the site layout: the header, footer and the site's own chrome
 * disappear on a soft 404 the visitor is meant to navigate away from.
 */
export default function SiteNotFound() {
  return <NotFoundView />;
}
