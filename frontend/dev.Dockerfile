# syntax=docker.io/docker/dockerfile:1

FROM oven/bun:alpine

RUN apk add --no-cache libc6-compat

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

COPY docker/dev-entrypoint.sh /usr/local/bin/dev-entrypoint.sh
RUN chmod +x /usr/local/bin/dev-entrypoint.sh

COPY . .

ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1

EXPOSE 3000

ENTRYPOINT ["/usr/local/bin/dev-entrypoint.sh"]
CMD ["bun", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]
