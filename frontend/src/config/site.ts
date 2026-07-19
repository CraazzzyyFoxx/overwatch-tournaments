export const SITE_NAME = process.env.NEXT_PUBLIC_SITE_NAME ?? "Anakq Tournaments";

// Public base URL for the frontend (used in metadata like Open Graph).
// Must be an absolute URL including protocol, e.g. "https://example.com".
export const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://owt.craazzzyyfoxx.me";

export const SITE_URL_OBJ = (() => {
	try {
		return new URL(SITE_URL);
	} catch {
		return new URL("https://owt.craazzzyyfoxx.me");
	}
})();

// Path to the main site icon (used for the header logo + metadata icon).
// Must be a file under `frontend/public` (e.g. "/logo.webp").
export const SITE_ICON = process.env.NEXT_PUBLIC_SITE_ICON ?? "/logo.webp";

// Browser favicon path (used for <link rel="icon">).
// Must be a file under `frontend/public` (e.g. "/favicon.ico").
export const SITE_FAVICON = process.env.NEXT_PUBLIC_SITE_FAVICON ?? "/favicon.ico";
