# syntax=docker/dockerfile:1.7

ARG COZE_SERVER_TAG=0.5.1
ARG COZE_WEB_TAG=0.5.1
ARG COZE_GIT_REF=v0.5.1
ARG ALPINE_VERSION=3.22.0

FROM cozedev/coze-studio-server:${COZE_SERVER_TAG} AS coze-server
FROM cozedev/coze-studio-web:${COZE_WEB_TAG} AS coze-web

FROM alpine:${ALPINE_VERSION}

ARG COZE_GIT_REF=v0.5.1
ARG TARGETARCH
ARG ALPINE_VERSION=3.22.0

LABEL org.opencontainers.image.title="Coze all-in-one HFS" \
      org.opencontainers.image.description="Hugging Face Docker Space wrapper for Coze Studio" \
      org.opencontainers.image.source="https://github.com/BlueSkyXN/Coze-all-in-one-HFS"

ENV HOME=/home/user \
    PATH=/app/.venv/bin:/home/user/.local/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    APP_PORT=7860 \
    DATA_DIR=/data/coze \
    COZE_APP_DIR=/app \
    COZE_WEB_DIR=/opt/coze-web \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

USER root

RUN apk add --no-cache \
      bash \
      ca-certificates \
      curl \
      jq \
      tzdata \
      procps \
      file \
      pax-utils \
      python3 \
      python3-dev \
      deno \
      nginx \
      supervisor \
      redis \
      mariadb \
      mariadb-client \
      nats-server \
      su-exec \
      shadow \
      tini \
    && update-ca-certificates

# Atlas CLI is used by Coze's official MySQL bootstrap flow. Keep it optional but available.
RUN curl -fsSL https://atlasgo.sh | sh -s -- -y --community || true \
    && if [ -x /root/.local/bin/atlas ]; then cp /root/.local/bin/atlas /usr/local/bin/atlas; fi

# MinIO fallback is optional. It is included to preserve the official local-storage route when no S3/TOS is configured.
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    case "$arch" in \
      amd64) minio_arch="amd64" ;; \
      arm64) minio_arch="arm64" ;; \
      *) echo "Unsupported TARGETARCH=$arch for MinIO download" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://dl.min.io/server/minio/release/linux-${minio_arch}/minio" -o /usr/local/bin/minio; \
    curl -fsSL "https://dl.min.io/client/mc/release/linux-${minio_arch}/mc" -o /usr/local/bin/mc; \
    chmod +x /usr/local/bin/minio /usr/local/bin/mc

RUN set -eux; \
    addgroup -g 1000 user || addgroup user; \
    adduser -D -u 1000 -G user -s /bin/bash user || adduser -D -G user -s /bin/bash user; \
    mkdir -p /data/coze /opt/coze-hfs/bin /opt/coze-hfs/conf /opt/coze/bootstrap /opt/coze-web /run/nginx /var/lib/nginx/tmp /var/log/nginx; \
    chown -R user:user /data /opt/coze-hfs /opt/coze /opt/coze-web /run/nginx /var/lib/nginx /var/log/nginx /home/user

COPY --from=coze-server /app /app
COPY --from=coze-web /usr/share/nginx/html/ /opt/coze-web/

# Fetch the DB bootstrap files corresponding to the selected Coze git tag.
RUN set -eux; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/volumes/mysql/schema.sql" -o /opt/coze/bootstrap/schema.sql; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/atlas/opencoze_latest_schema.hcl" -o /opt/coze/bootstrap/opencoze_latest_schema.hcl; \
    chown -R user:user /app /opt/coze /opt/coze-web

COPY hfs/bin/ /opt/coze-hfs/bin/
COPY hfs/conf/ /opt/coze-hfs/conf/

RUN chmod +x /opt/coze-hfs/bin/*.sh \
    && chown -R user:user /opt/coze-hfs /app /opt/coze /opt/coze-web

USER user
WORKDIR /app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD /opt/coze-hfs/bin/healthcheck.sh

ENTRYPOINT ["/sbin/tini", "--", "/opt/coze-hfs/bin/entrypoint.sh"]
