FROM mcr.microsoft.com/devcontainers/python:3.14-trixie

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        autoconf \
        ffmpeg \
        libavcodec-dev \
        libavdevice-dev \
        libavfilter-dev \
        libavformat-dev \
        libavutil-dev \
        libffi-dev \
        libjpeg-dev \
        libssl-dev \
        libudev-dev \
        libxml2-dev \
        libxslt1-dev \
        pkg-config \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

USER vscode

RUN mkdir -p /home/vscode/.claude

COPY requirements.test.txt /tmp/requirements.test.txt

RUN python -m pip install --no-cache-dir \
    -r /tmp/requirements.test.txt \
    mypy \
    ruff
