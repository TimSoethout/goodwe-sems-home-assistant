FROM ghcr.io/astral-sh/uv:0.13.6-python3.14-trixie-slim

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/workspaces/.venv

WORKDIR /workspaces

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf \
        build-essential \
        ffmpeg \
        gh \
        git \
        libavcodec-dev \
        libavdevice-dev \
        libavfilter-dev \
        libavformat-dev \
        libavutil-dev \
        libffi-dev \
        libjpeg-dev \
        libpcap0.8t64 \
        libssl-dev \
        libturbojpeg0 \
        libudev-dev \
        libxml2-dev \
        libxslt1-dev \
        pkg-config \
        unzip \
        wget \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /root/.claude
