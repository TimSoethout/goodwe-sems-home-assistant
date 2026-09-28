FROM mcr.microsoft.com/devcontainers/python:3.14-trixie

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf \
        curl \
        ffmpeg \
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

ARG TARGETARCH

RUN case "$TARGETARCH" in \
        amd64) go2rtc_sha256=32d616af226bd731678ffde328b94cfb94e30339bfefc469cfb76323144615a6 ;; \
        arm64) go2rtc_sha256=359fabade8a7a51e81a55fe6df6b0ef81764a5e1d63179577534eaaa71904b50 ;; \
        *) echo "Unsupported architecture for go2rtc: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl --fail --location --silent --show-error \
        "https://github.com/AlexxIT/go2rtc/releases/download/v1.9.14/go2rtc_linux_${TARGETARCH}" \
        --output /usr/local/bin/go2rtc \
    && echo "$go2rtc_sha256  /usr/local/bin/go2rtc" | sha256sum --check --status \
    && chmod 0755 /usr/local/bin/go2rtc

USER vscode

RUN mkdir -p /home/vscode/.claude

COPY requirements.test.txt /tmp/requirements.test.txt

RUN python -m pip install --no-cache-dir \
    -r /tmp/requirements.test.txt \
    mypy \
    ruff
