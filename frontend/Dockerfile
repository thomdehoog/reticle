# The Reticle web tier: Caddy serving the built frontend and proxying /api.
#
# Build from the repository root:
#
#   docker build -f frontend/Dockerfile -t reticle-web .
#
# or simply `docker compose build`.
#
# Author: Thom de Hoog <thom.dehoog@zmb.uzh.ch>, <thomdehoog@gmail.com>

# Readable tags; Dependabot proposes updates. Any of the three can be pinned
# to exact bytes by appending @sha256:<digest> (see backend/Dockerfile). The
# npm packages are pinned to hashes by package-lock.json, which `npm ci`
# enforces.
ARG NODE_IMAGE=node:22-bookworm-slim
ARG CADDY_IMAGE=caddy:2.11-alpine
ARG ALPINE_IMAGE=alpine:3.22


# ---------------------------------------------------------------------------
# Stage 1: build the static site. Node exists only here; nothing of it ships.
# The output is plain files, identical for every CPU architecture, so this
# stage always runs natively even when the image is being built for another.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS build

WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

COPY frontend/ ./
# `vite build` only. The typecheck and the unit tests are CI's job; an image
# build should not fail on a type error in a test file.
RUN npx vite build


# ---------------------------------------------------------------------------
# Stage 2: the Caddy binary, without its file capability.
#
# The official image gives /usr/bin/caddy the cap_net_bind_service file
# capability so that root is not needed for ports 80 and 443. This stack drops
# every capability instead, and the kernel refuses to execute a binary whose
# file capabilities cannot be granted. `cp` writes a new file without the
# extended attribute; that copy is what ships. (Ports below 1024 are opened to
# the unprivileged user by a namespaced sysctl in compose.yaml.)
FROM ${CADDY_IMAGE} AS caddy

RUN mkdir /out \
 && cp /usr/bin/caddy /out/caddy \
 && { cp /etc/mime.types /out/mime.types 2>/dev/null || : > /out/mime.types; }


# ---------------------------------------------------------------------------
# Stage 3: the image that runs. A bare Alpine rather than the Caddy image
# itself, because rewriting the binary on top of that image would ship it
# twice (50 MB each).
FROM ${ALPINE_IMAGE}

ARG RETICLE_VERSION=dev

COPY --from=caddy /out/caddy /usr/bin/caddy
COPY --from=caddy /out/mime.types /etc/mime.types

RUN mkdir -p /data/caddy /config/caddy \
 && chown -R 10002:10002 /data /config

ENV XDG_DATA_HOME=/data \
    XDG_CONFIG_HOME=/config

COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/caddy/modes /etc/caddy/modes
COPY --from=build /src/dist /srv

# A Caddyfile with a mistake in it should fail the build, not the deployment.
RUN for mode in off internal auto; do \
      RETICLE_DOMAIN=reticle.example.org RETICLE_TLS_MODE="$mode" \
      XDG_DATA_HOME=/tmp XDG_CONFIG_HOME=/tmp \
        caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null \
      || exit 1; \
    done

LABEL org.opencontainers.image.title="Reticle web" \
      org.opencontainers.image.description="Guides and wiki pages for a microscopy facility: Caddy and the built frontend." \
      org.opencontainers.image.source="https://github.com/thomdehoog/reticle" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${RETICLE_VERSION}"

USER 10002:10002
VOLUME ["/data", "/config"]
EXPOSE 80 443 443/udp

# Port 9180 is an internal listener that proxies exactly /api/health, so
# "healthy" means Caddy is up AND can reach the API. busybox wget is part of
# Alpine; nothing is added for this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --start-interval=2s --retries=3 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:9180/api/health"]

CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
