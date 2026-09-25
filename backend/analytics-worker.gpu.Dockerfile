FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app/

# Install uv.
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /uvx /bin/

ENV PATH="/app/.venv/bin:$PATH"
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ARG APP_PATH=analytics

# LightGBM's CUDA build requires the full CUDA toolkit. For the worker image we
# build the OpenCL GPU variant, which works with NVIDIA GPUs through the driver
# exposed by Docker's NVIDIA runtime. XGBoost uses its CUDA-enabled Linux wheel.
RUN set -eux; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; \
    for attempt in 1 2 3; do \
        if apt-get update -o Acquire::Retries=3 \
            && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends -o Acquire::Retries=3 \
                build-essential \
                ca-certificates \
                cmake \
                git \
                libboost-filesystem-dev \
                libboost-system-dev \
                libgomp1 \
                ocl-icd-libopencl1 \
                ocl-icd-opencl-dev \
                opencl-headers; then \
            break; \
        fi; \
        if [ "${attempt}" -eq 3 ]; then \
            exit 1; \
        fi; \
        sleep "$((attempt * 5))"; \
    done; \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock /app/

COPY app-service/pyproject.toml /app/app-service/pyproject.toml
COPY identity-service/pyproject.toml /app/identity-service/pyproject.toml
COPY parser-service/pyproject.toml /app/parser-service/pyproject.toml
COPY tournament-service/pyproject.toml /app/tournament-service/pyproject.toml
COPY discord-service/pyproject.toml /app/discord-service/pyproject.toml
COPY balancer-service/pyproject.toml /app/balancer-service/pyproject.toml
COPY analytics-service/pyproject.toml /app/analytics-service/pyproject.toml
COPY stream-service/pyproject.toml /app/stream-service/pyproject.toml

COPY ./shared /app/shared

# The lock pins xgboost-cpu (what the shipped CPU image runs); this image needs
# the CUDA build of the same `xgboost` module instead, so the lock's package is
# skipped here and in the final sync, and the CUDA wheel (with nvidia-nccl-cu12)
# is installed on top.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --package analytics-service \
        --no-install-package xgboost-cpu

ARG XGBOOST_VERSION=3.2.0

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install "xgboost==${XGBOOST_VERSION}"

ARG LIGHTGBM_VERSION=4.6.0

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install \
        --force-reinstall \
        --no-deps \
        --no-binary lightgbm \
        --config-settings=cmake.define.USE_GPU=ON \
        "lightgbm==${LIGHTGBM_VERSION}"

ENV PYTHONPATH=/app/analytics-service:/app

COPY ./scripts /app/scripts
COPY ./analytics-service /app/analytics-service

# ``--inexact``: an exact sync would remove the CUDA xgboost installed above,
# which is not in the lock.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --inexact --package analytics-service \
        --no-install-package xgboost-cpu

WORKDIR /app/analytics-service

RUN mkdir -p /logs
