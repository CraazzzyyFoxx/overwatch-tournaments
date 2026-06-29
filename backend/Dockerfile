FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app/

# Install uv
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

# Copy workspace root configuration and lockfile
COPY pyproject.toml uv.lock /app/

# Copy all workspace member pyproject.toml files (required for workspace resolution)
COPY app-service/pyproject.toml /app/app-service/pyproject.toml
COPY identity-service/pyproject.toml /app/identity-service/pyproject.toml
COPY parser-service/pyproject.toml /app/parser-service/pyproject.toml
COPY tournament-service/pyproject.toml /app/tournament-service/pyproject.toml
COPY discord-service/pyproject.toml /app/discord-service/pyproject.toml
COPY balancer-service/pyproject.toml /app/balancer-service/pyproject.toml
COPY analytics-service/pyproject.toml /app/analytics-service/pyproject.toml

ARG APP_PATH

# System build deps are installed BEFORE copying ./shared so that frequent
# changes to shared source do not invalidate these layers and force a costly
# re-download/re-install of the Rust/OpenMP toolchain.
RUN if [ "${APP_PATH}" = "balancer" ]; then \
        set -eux; \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
        for attempt in 1 2 3; do \
            if apt-get update -o Acquire::Retries=3 \
                && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Acquire::Retries=3 build-essential cargo rustc; then \
                break; \
            fi; \
            if [ "${attempt}" -eq 3 ]; then \
                exit 1; \
            fi; \
            sleep "$((attempt * 5))"; \
        done; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# analytics-service: LightGBM + XGBoost link against the GCC OpenMP runtime
# (libgomp1) which the slim base image does not ship. Without it, importing
# lightgbm fails with: ``OSError: libgomp.so.1: cannot open shared object file``.
RUN if [ "${APP_PATH}" = "analytics" ]; then \
        set -eux; \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
        for attempt in 1 2 3; do \
            if apt-get update -o Acquire::Retries=3 \
                && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Acquire::Retries=3 libgomp1; then \
                break; \
            fi; \
            if [ "${attempt}" -eq 3 ]; then \
                exit 1; \
            fi; \
            sleep "$((attempt * 5))"; \
        done; \
        rm -rf /var/lib/apt/lists/*; \
    fi

# `shared` is a workspace member; its source is required to build its wheel during `uv sync`.
COPY ./shared /app/shared

# Install dependencies for the target service only
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --package ${APP_PATH}-service

ENV PYTHONPATH=/app/${APP_PATH}-service:/app

# Copy scripts and configuration
COPY ./scripts /app/scripts

# Copy the specific service code
COPY ./${APP_PATH}-service /app/${APP_PATH}-service

# Sync the project (install the package itself)
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ${APP_PATH}-service

# Build the moo_core Rust extension. Cargo's crate registry/git caches and the
# build target dir are persisted across builds via BuildKit cache mounts, so
# crates are downloaded once and compilation is incremental. maturin is already
# installed into the venv by `uv sync` (it is a Linux dependency of the service),
# so call it directly instead of bootstrapping a throwaway env via `uvx`.
RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/app/balancer-service/native/moo_core/target \
    if [ "${APP_PATH}" = "balancer" ]; then \
        maturin develop \
            --release \
            --features extension-module \
            --manifest-path /app/balancer-service/native/moo_core/Cargo.toml; \
    fi

# Set working directory to the service
WORKDIR /app/${APP_PATH}-service

# Create logs directory
RUN mkdir -p /logs

# Health check — hits the /health endpoint exposed by each service
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1
