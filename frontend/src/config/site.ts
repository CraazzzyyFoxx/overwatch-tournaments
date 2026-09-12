export const SITE_NAME = process.env.NEXT_PUBLIC_SITE_NAME ?? "OWT";

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

// Google Analytics measurement id (e.g. "G-XXXXXXXXXX"). Unset disables GA.
export const GA_ID = process.env.NEXT_PUBLIC_GA_ID;

// Yandex Metrica counter id (numeric). Unset disables Metrica.
export const YM_ID = process.env.NEXT_PUBLIC_YM_ID;

// Release version shown in the footer. CI passes the deployed git tag
// (`v1.2.3`) as a build arg, so it is baked into the bundle; unset in local
// dev, where the footer then renders no version at all.
export const APP_VERSION = process.env.NEXT_PUBLIC_APP_VERSION;

// Discord application id of the platform's bot — the `client_id` of the bot
// invite link on the workspace Discord settings page. It is the APPLICATION id
// (same app the bot token belongs to), not the bot user id, and not necessarily
// the OAuth login client id if login runs on a separate app. Unset hides the
// invite button rather than emitting a link Discord answers with "invalid
// application".
export const DISCORD_CLIENT_ID = process.env.NEXT_PUBLIC_DISCORD_CLIENT_ID;
