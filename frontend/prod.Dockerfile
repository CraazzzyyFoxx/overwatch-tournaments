# syntax=docker.io/docker/dockerfile:1

# 1. Install dependencies with Bun (fast)
FROM oven/bun:alpine AS deps

RUN apk add --no-cache libc6-compat

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# 2. Build with Bun
FROM oven/bun:alpine AS builder

RUN apk add --no-cache libc6-compat

WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Only NEXT_PUBLIC_* values are baked into the client bundle at build time. API
# base URLs are gone — the browser uses relative, same-origin gateway paths.
ARG NEXT_PUBLIC_CACHE_POLICY
ARG NEXT_PUBLIC_SITE_NAME
ARG NEXT_PUBLIC_SITE_URL
ARG NEXT_PUBLIC_SITE_ICON
ARG NEXT_PUBLIC_SITE_FAVICON

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_PUBLIC_CACHE_POLICY=${NEXT_PUBLIC_CACHE_POLICY}
ENV NEXT_PUBLIC_SITE_NAME=${NEXT_PUBLIC_SITE_NAME}
ENV NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL}
ENV NEXT_PUBLIC_SITE_ICON=${NEXT_PUBLIC_SITE_ICON}
ENV NEXT_PUBLIC_SITE_FAVICON=${NEXT_PUBLIC_SITE_FAVICON}

RUN bun run build

# 3. Production runtime with Node.js (Next.js server requires Node)
FROM node:22-alpine AS runner
WORKDIR /app

# Internal gateway base for server-side fetches (SSR + route handlers +
# middleware). Runtime value; compose overrides it with the gateway service URL.
ARG NEXT_INTERNAL_API_URL=http://gateway:8080

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV NEXT_INTERNAL_API_URL=${NEXT_INTERNAL_API_URL}

RUN addgroup -g 1001 -S nodejs
RUN adduser -S nextjs -u 1001

COPY --from=builder /app/public ./public

# Automatically leverage output traces to reduce image size
# https://nextjs.org/docs/advanced-features/output-file-tracing
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000

CMD HOSTNAME="0.0.0.0" node server.js
