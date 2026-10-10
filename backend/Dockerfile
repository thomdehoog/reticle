# The Reticle API: FastAPI under uvicorn, as an unprivileged user.
#
# Build from the repository root (the context is the root so that the image can
# take its entrypoint from deploy/docker):
#
#   docker build -f backend/Dockerfile -t reticle-app .
#
# or simply `docker compose build`.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

# Minor version and distribution are pinned; patch releases of the base image
# arrive on rebuild, and Dependabot proposes the next minor.
#
# To pin the base image to exact bytes, append its digest:
#
#   ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:<digest>
#
# (find it with `docker buildx imagetools inspect python:3.13-slim-bookworm`).
# The price is that security fixes to the base image then arrive only when
# somebody — or Dependabot — moves the digest. The Python packages below are
# pinned to hashes either way.
ARG PYTHON_IMAGE=python:3.13-slim-bookworm


# ---------------------------------------------------------------------------
# Stage 1: install the dependencies into a virtual environment. Compilers and
# pip's cache stay in this stage; only the finished environment is copied on.
FROM ${PYTHON_IMAGE} AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN python -m venv /opt/venv

# Only the lock file, so this layer is rebuilt when the dependencies change
# and not every time a line of application code does.
#
# requirements.lock is requirements.txt resolved to exact versions, every one
# with the hashes of its published files (pip-compile; the command is in the
# lock file's header and in docs/MAINTENANCE.md, section 5). --require-hashes makes pip
# refuse anything that is not in the lock or whose bytes differ from what was
# locked: a build next month installs what was tested this month, and a
# tampered or re-uploaded package fails the build instead of entering it.
COPY backend/requirements.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    /opt/venv/bin/pip install --require-hashes -r /tmp/requirements.lock \
 && /opt/venv/bin/pip check \
 && rm -rf /opt/venv/lib/python*/site-packages/pip \
           /opt/venv/lib/python*/site-packages/pip-*.dist-info \
           /opt/venv/bin/pip*


# ---------------------------------------------------------------------------
# Stage 2: the image that runs.
FROM ${PYTHON_IMAGE}

ARG RETICLE_VERSION=dev

# tini            reaps children and forwards signals, so `docker stop` is a
#                 clean shutdown and not a ten-second wait followed by SIGKILL.
# fonts-dejavu    the PDF export needs glyphs the font bundled with ReportLab
#                 lacks: λ, Å, ≥, →. Without it those print as boxes.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 reticle \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --home-dir /app \
            --shell /usr/sbin/nologin reticle \
 && mkdir -p /data/media /data/tmp \
 && chown -R 10001:10001 /data

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY deploy/docker/app-entrypoint.sh /usr/local/bin/reticle-entrypoint
COPY deploy/docker/dbtool.py /usr/local/lib/reticle/dbtool.py

# The root filesystem is mounted read-only at run time, so bytecode is compiled
# now; otherwise every start would recompile everything in memory.
RUN chmod 0755 /usr/local/bin/reticle-entrypoint \
 && /opt/venv/bin/python -m compileall -q app migrations

# RETICLE_ENV_FILE is empty on purpose: configuration comes from the container
# environment only, never from a stray .env inside the image.
# TMPDIR is on the data volume, not on a RAM-backed /tmp: a video upload is
# spooled there before it is copied into the media root, and 200 MB per
# concurrent upload should cost disk, not memory.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RETICLE_ENV_FILE= \
    RETICLE_DATABASE_URL=sqlite:////data/reticle.db \
    RETICLE_MEDIA_ROOT=/data/media \
    TMPDIR=/data/tmp \
    RETICLE_IMAGE_VERSION=${RETICLE_VERSION}

LABEL org.opencontainers.image.title="Reticle API" \
      org.opencontainers.image.description="Guides and wiki pages for a microscopy facility: the API." \
      org.opencontainers.image.source="https://github.com/thomdehoog/reticle" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${RETICLE_VERSION}"

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8000

# Standard library only: no curl in the image just to ask one question.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --start-interval=2s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["tini", "--", "reticle-entrypoint"]
CMD ["serve"]
