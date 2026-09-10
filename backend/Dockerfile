FROM python:3.14-slim

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

# The 30s default is per HTTP request, not per byte, so the two biggest wheels
# in this workspace time out on an ordinary link and fail the whole build:
# nvidia-nccl-cu12 (~286 MiB, pulled in by xgboost) for analytics-svc and
# cmake (~90 MiB, a build-system.requires of mix-balancer) for balancer-svc.
# Fewer parallel streams so those two get the bandwidth instead of racing a
# dozen small downloads for it.
ENV UV_HTTP_TIMEOUT=300
ENV UV_CONCURRENT_DOWNLOADS=4

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
COPY stream-service/pyproject.toml /app/stream-service/pyproject.toml

ARG APP_PATH

# System build deps are installed BEFORE copying ./shared so that frequent
# changes to shared source do not invalidate these layers and force a costly
# re-download/re-install of the Rust/OpenMP toolchain.
# ``mix-balancer`` (vendored under balancer-service/native/mix_balancer,
# see its README for provenance) is built via scikit-build-core during
# ``uv sync`` below -- needs ``cmake``/``ninja-build`` to configure (no
# ``git``: it's a local path dependency, not fetched).
RUN if [ "${APP_PATH}" = "balancer" ]; then \
        set -eux; \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
        for attempt in 1 2 3; do \
            if apt-get update -o Acquire::Retries=3 \
                && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Acquire::Retries=3 build-essential cargo rustc cmake ninja-build; then \
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
# build-essential is required because `ruptures` has no Python 3.14 wheel yet
# (upstream: https://github.com/deepcharles/ruptures) — uv falls back to
# building its sdist, which needs a C compiler for the `ekcpd` extension.
# Drop build-essential once ruptures ships a cp314 wheel.
RUN if [ "${APP_PATH}" = "analytics" ]; then \
        set -eux; \
        sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
        for attempt in 1 2 3; do \
            if apt-get update -o Acquire::Retries=3 \
                && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Acquire::Retries=3 libgomp1 build-essential; then \
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

# ``mix-balancer`` is a local path dependency (balancer-service/pyproject.toml's
# [tool.uv.sources]) -- unlike registry/git dependencies, uv needs its actual
# source present to resolve it, so it must land before the first `uv sync`
# below runs (that step only has pyproject.toml files copied so far, see
# line ~26). Copied unconditionally: it's a few small files, and every other
# ``${APP_PATH}`` build simply never references this package.
COPY ./balancer-service/native/mix_balancer /app/balancer-service/native/mix_balancer

# Install dependencies for the target service only
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
#
# ``--no-install-package nvidia-nccl-cu12``: xgboost declares it on Linux, but it
# is a ~300 MiB multi-GPU collective-communications library, and these images run
# on GPU-less boxes where XGBoost trains with ``device="cpu"`` and never dlopens
# it. Skipping the install skips the download, which is what actually failed the
# build. The lock is untouched, so ``analytics-worker.gpu.Dockerfile`` -- the one
# image that does get a GPU -- still installs it by simply not passing this flag.
# The flag is harmless for the services whose tree never contained the package.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --package ${APP_PATH}-service \
        --no-install-package nvidia-nccl-cu12

ENV PYTHONPATH=/app/${APP_PATH}-service:/app

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

# Sync the project (install the package itself)
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#intermediate-layers
# Same GPU exclusion as the dependency layer above — without it here, this sync
# would pull the wheel the previous one skipped.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --package ${APP_PATH}-service \
        --no-install-package nvidia-nccl-cu12

# Build the tournament_balancer Rust extension (native/tournament_balancer). Cargo's
# crate registry/git caches and the build target dir are persisted across
# builds via BuildKit cache mounts, so crates are downloaded once and
# compilation is incremental. maturin is already installed into the venv by
# `uv sync` (it is a Linux dependency of the service), so call it directly
# instead of bootstrapping a throwaway env via `uvx`.
RUN --mount=type=cache,target=/root/.cargo/registry \
    --mount=type=cache,target=/root/.cargo/git \
    --mount=type=cache,target=/app/balancer-service/native/tournament_balancer/target \
    if [ "${APP_PATH}" = "balancer" ]; then \
        maturin develop \
            --release \
            --features extension-module \
            --manifest-path /app/balancer-service/native/tournament_balancer/Cargo.toml; \
    fi

# Set working directory to the service
WORKDIR /app/${APP_PATH}-service

# Create logs directory
RUN mkdir -p /logs

# Health check — hits the /health endpoint exposed by each service
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT:-8000}/health')" || exit 1
