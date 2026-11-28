# Uploaded images without the CDN: release note

**Why.** Uploaded images (avatars, team and tournament logos, catalog, division grids, achievements) were served by the
Timeweb CDN `cdn.craazzzyyfoxx.me` in front of the S3 bucket. Its edges failed the frontend's image optimizer in
bursts (`Can't load image https://cdn.craazzzyyfoxx.me/…: fetch failed`, 73 in 72 hours on 2026-11-28).

**Now.** nginx on the production host serves the bucket at `https://owt.craazzzyyfoxx.me/media/<key>` with an on-disk
cache (`media` zone, 5 GB): a copy is fresh for 1 hour, then revalidated against S3 by ETag, and served stale for up
to 30 days while S3 errors. Browsers get `max-age=31536000, immutable` for `avatars/` (content-hashed keys) and
`max-age=3600, stale-while-revalidate=86400` for the rest. `/_next/image` results are cached by nginx too (`img`
zone, keyed by query and output format, freshness from the frontend's `Cache-Control`), so a deploy no longer drops
them. Both caches live in the `owt_nginx-cache` volume. The optimizer reaches `/media` through the host's own address,
not through DDoS-Guard.

**Cutover on the production host** (after the release is deployed):

1. `backend/env/common.env`: `S3_PUBLIC_URL=https://owt.craazzzyyfoxx.me/media` (back up the file first), then
   recreate the backend services so new uploads get the new base.
2. Rewrite stored URLs, dry run first:
   `python -m scripts.rewrite_s3_public_url --old https://cdn.craazzzyyfoxx.me --dry-run`, then without `--dry-run`.
3. Switch the CDN resource off in the Timeweb panel once pages show images from `/media`.

`https://cdn.craazzzyyfoxx.me/**` stays in `NEXT_PUBLIC_IMAGE_REMOTE_PATTERNS` for URLs kept in history (audit,
outbox, Discord payloads), which the rewrite leaves alone.

**Rollback.** Restore `S3_PUBLIC_URL` and run the rewrite with `--old https://owt.craazzzyyfoxx.me/media --new
https://cdn.craazzzyyfoxx.me`. `/media` keeps working either way.
