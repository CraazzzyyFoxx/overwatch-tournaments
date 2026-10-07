# Three stages, and only the last one ships:
#
#   builder  compilers (Rust, C) + the third-party venv they build
#   native   the balancer_native Rust wheel (balancer only)
#   runtime  python:3.14-slim + that venv + source
#
# The compilers used to live in the shipped image: ~1 GiB of balancer's and
# ~400 MiB of analytics' that every production host pulled and never ran.
#
# Layer order is the other half. The venv is the one big layer (hundreds of MiB
# for analytics) and it depends on uv.lock + pyproject files alone, so a release
# that touches shared/ or service code re-pulls a few MiB of source, not the
# venv. Nothing that changes per release may be copied before it.
# Digest-pinned: a re-published 3.14-slim rebuilds every layer above it and the
# host re-pulls every venv. Dependabot (docker, /backend) bumps it as a PR.
FROM python:3.14-slim@sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d AS base

ENV PYTHONUNBUFFERED=1

WORKDIR /app/

# Install uv. Kept in the runtime image: runbooks `docker compose exec <svc> uv run ...`.
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

# The 30s default is per HTTP request, not per byte, so a big wheel times out on
# an ordinary link and fails the whole build. Fewer parallel streams so it gets
# the bandwidth instead of racing a dozen small downloads.
ENV UV_HTTP_TIMEOUT=300
ENV UV_CONCURRENT_DOWNLOADS=4


FROM base AS builder

ARG APP_PATH

# balancer: the ``balancer_native`` Rust extension needs cargo/rustc and a C
# linker (gcc + libc6-dev); nothing in the crate compiles C or C++.
# analytics: `ruptures` has no Python 3.14 wheel yet
# (upstream: https://github.com/deepcharles/ruptures), so uv builds its sdist,
# which needs a C compiler for the `ekcpd` extension.
RUN set -eux; \
    case "${APP_PATH}" in \
        balancer) pkgs="cargo rustc gcc libc6-dev" ;; \
        analytics) pkgs="build-essential" ;; \
        *) exit 0 ;; \
    esac; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    for attempt in 1 2 3; do \
        if apt-get update -o Acquire::Retries=3 \
            && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Acquire::Retries=3 ${pkgs}; then \
            break; \
        fi; \
        if [ "${attempt}" -eq 3 ]; then \
            exit 1; \
        fi; \
        sleep "$((attempt * 5))"; \
    done; \
    rm -rf /var/lib/apt/lists/*

# Workspace root, lockfile and every member's pyproject.toml (required for
# workspace resolution) -- metadata only, no source.
COPY pyproject.toml uv.lock /app/
COPY shared/pyproject.toml /app/shared/pyproject.toml
COPY app-service/pyproject.toml /app/app-service/pyproject.toml
COPY identity-service/pyproject.toml /app/identity-service/pyproject.toml
COPY parser-service/pyproject.toml /app/parser-service/pyproject.toml
COPY tournament-service/pyproject.toml /app/tournament-service/pyproject.toml
COPY discord-service/pyproject.toml /app/discord-service/pyproject.toml
COPY balancer-service/pyproject.toml /app/balancer-service/pyproject.toml
COPY analytics-service/pyproject.toml /app/analytics-service/pyproject.toml
COPY stream-service/pyproject.toml /app/stream-service/pyproject.toml

# Third-party dependencies of the target service only. ``--no-install-workspace``
# (not ``--no-install-project``) keeps ``shared`` -- a workspace member -- out,
# so its source is not needed here and changing it does not rebuild this layer.
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package ${APP_PATH}-service


FROM builder AS native

ARG APP_PATH

# The balancer_native Rust extension (both engines), as a wheel the runtime
# stage installs in its own small layer -- so a Rust change neither rebuilds nor
# re-ships the venv. Cargo's registry/git caches and the target dir are
# BuildKit cache mounts. maturin comes from the venv. ``linux`` tag: the wheel
# is only ever installed into this same base image, so there is nothing to
# audit for manylinux. No ``target-cpu``: the image is built on a CI runner and
# run on a different production CPU.
COPY ./balancer-service/native/balancer_native /src/balancer_native
RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/src/balancer_native/target \
    mkdir /wheels; \
    if [ "${APP_PATH}" = "balancer" ]; then \
        maturin build \
            --release \
            --features extension-module \
            --compatibility linux \
            --interpreter /app/.venv/bin/python \
            --manifest-path /src/balancer_native/Cargo.toml \
            --out /wheels; \
    fi


FROM base AS runtime

ARG APP_PATH

# analytics: LightGBM + XGBoost link against the GCC OpenMP runtime (libgomp1),
# which the slim base image does not ship. Without it, importing lightgbm fails
# with: ``OSError: libgomp.so.1: cannot open shared object file``.
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

# The venv plus the metadata it was synced from (lock, pyproject files): the
# one big layer, reused until the lock changes.
COPY --from=builder /app /app

RUN --mount=type=bind,from=native,source=/wheels,target=/wheels \
    if [ "${APP_PATH}" = "balancer" ]; then \
        uv pip install --python /app/.venv/bin/python --no-deps /wheels/*.whl; \
    fi

ENV PYTHONPATH=/app/${APP_PATH}-service:/app

# `shared` is a workspace member; its source is required to install it below.
COPY ./shared /app/shared

# Copy scripts and configuration
COPY ./scripts /app/scripts

# Copy alembic config + migrations so `alembic upgrade head` works inside the
# container regardless of which service's WORKDIR is active (see alembic.ini's
# %(here)s-anchored script_location plus ALEMBIC_CONFIG below).
COPY alembic.ini /app/alembic.ini
COPY ./migrations /app/migrations
ENV ALEMBIC_CONFIG=/app/alembic.ini

# Copy the specific service code
COPY ./${APP_PATH}-service /app/${APP_PATH}-service

# Install the workspace members themselves (editable `shared`; pure Python, no
# compiler needed). ``--inexact`` keeps balancer_native, which is not in the
# lock and an exact sync would remove.
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --inexact --package ${APP_PATH}-service

# The venv is complete at this point. Without this, `uv run` inside a container
# re-syncs and adds the dev group (network downloads).
ENV UV_NO_SYNC=1

# Set working directory to the service
WORKDIR /app/${APP_PATH}-service

# Create logs directory
RUN mkdir -p /logs

# Health check — hits the /health endpoint exposed by each service
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1
