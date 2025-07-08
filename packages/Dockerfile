FROM python:3.13-slim-bullseye

ENV DEBIAN_FRONTEND=noninteractive
ENV EXIFTOOL_PATH=/usr/bin/exiftool
ENV FFMPEG_PATH=/usr/bin/ffmpeg
ENV MARKITDOWN_ENABLE_PLUGINS=True

# Runtime dependency
# NOTE: Add any additional MarkItDown plugins here
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    exiftool \
    git

# Cleanup
RUN rm -rf /var/lib/apt/lists/*


COPY . /app

WORKDIR /app/markitdown-api
RUN pip --no-cache-dir install .

WORKDIR /markitdown-api

# Default USERID and GROUPID
ARG USERID=nobody
ARG GROUPID=nogroup

USER $USERID:$GROUPID

EXPOSE 8000

ENTRYPOINT ["markitdown-api"]
