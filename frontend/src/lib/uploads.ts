/**
 * Max avatar upload size (bytes), shared by the self-service (My Account) and
 * admin (PlayerProfileDialog) editors. Keep in sync with the backend
 * `MAX_AVATAR_SIZE` (shared/clients/s3/upload.py) — the client rejects oversized
 * files up front (with a visible message) so a doomed upload never leaves the
 * browser, but the server enforces the real limit.
 */
export const MAX_AVATAR_BYTES = 5 * 1024 * 1024; // 5 MB

/**
 * Shared by the achievement create form (achievements list page) and the
 * achievement edit form ([id] page): the accepted image types, the max
 * upload size, and the fixed preview thumbnail class both forms render at.
 */
export const ACHIEVEMENT_IMAGE_ACCEPT = "image/webp,image/png,image/jpeg,image/gif";
export const MAX_ACHIEVEMENT_IMAGE_BYTES = 5 * 1024 * 1024; // 5 MB
export const ACHIEVEMENT_IMAGE_PREVIEW_CLASS = "h-16 w-16 rounded-lg object-cover border";
