FROM python:3.13-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV EXIFTOOL_PATH=/usr/bin/exiftool
ENV EXIFTOOL_MIN_VERSION=12.24
ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV MARKITDOWN_ENABLE_PLUGINS=True

# Runtime dependency
# NOTE: Add any additional MarkItDown plugins here
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libimage-exiftool-perl

RUN python -c 'import os, subprocess, sys; min_version = tuple(map(int, os.environ["EXIFTOOL_MIN_VERSION"].split("."))); version_output = subprocess.check_output(["exiftool", "-ver"], text=True).strip(); version = tuple(map(int, version_output.split("."))); sys.exit(0 if version >= min_version else "ExifTool " + version_output + " is older than required " + os.environ["EXIFTOOL_MIN_VERSION"])'

# Cleanup
RUN rm -rf /var/lib/apt/lists/*

COPY . /app
RUN pip --no-cache-dir install /app

WORKDIR /workdir

# Default USERID and GROUPID
ARG USERID=nobody
ARG GROUPID=nogroup

USER $USERID:$GROUPID

ENTRYPOINT [ "markitdown-mcp" ]
