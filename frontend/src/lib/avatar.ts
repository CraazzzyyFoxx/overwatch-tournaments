/**
 * Max avatar upload size (bytes), shared by the self-service (My Account) and
 * admin (PlayerProfileDialog) editors. Keep in sync with the backend
 * `MAX_AVATAR_SIZE` (shared/clients/s3/upload.py) — the client rejects oversized
 * files up front (with a visible message) so a doomed upload never leaves the
 * browser, but the server enforces the real limit.
 */
export const MAX_AVATAR_BYTES = 5 * 1024 * 1024; // 5 MB
