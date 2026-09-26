import { NotFoundView } from "@/components/NotFoundView";

/**
 * Root 404: URLs that match no route at all. Rendered under `app/layout.tsx`
 * only — no site header or footer. A `notFound()` from a (site) page hits
 * `app/(site)/not-found.tsx` instead, which keeps that chrome.
 */
export default function NotFound() {
  return <NotFoundView />;
}
