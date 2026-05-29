# syntax=docker/dockerfile:1.7

ARG COZE_SERVER_TAG=0.5.1
ARG COZE_WEB_TAG=0.5.1
ARG COZE_GIT_REF=v0.5.1
ARG ELASTICSEARCH_IMAGE=bitnamilegacy/elasticsearch:8.18.0
ARG ETCD_IMAGE=bitnamilegacy/etcd:3.5
ARG MILVUS_IMAGE=milvusdb/milvus:v2.5.10

FROM cozedev/coze-studio-server:${COZE_SERVER_TAG} AS coze-server
FROM cozedev/coze-studio-web:${COZE_WEB_TAG} AS coze-web
FROM ${ETCD_IMAGE} AS etcd
FROM ${MILVUS_IMAGE} AS milvus

FROM ${ELASTICSEARCH_IMAGE}

ARG COZE_GIT_REF=v0.5.1
ARG TARGETARCH
ARG DENO_VERSION=2.4.5
ARG DENO_SHA256_AMD64=
ARG DENO_SHA256_ARM64=
ARG ATLAS_INSTALL_URL=https://atlasgo.sh
ARG ATLAS_INSTALL_SHA256=
ARG INSTALL_ATLAS=true
ARG MINIO_SHA256_AMD64=
ARG MINIO_SHA256_ARM64=
ARG MC_SHA256_AMD64=
ARG MC_SHA256_ARM64=

LABEL org.opencontainers.image.title="Coze all-in-one HFS" \
      org.opencontainers.image.description="Hugging Face Docker Space wrapper for Coze Studio" \
      org.opencontainers.image.source="https://github.com/BlueSkyXN/Coze-all-in-one-HFS"

ENV HOME=/home/user \
    PATH=/app/.venv/bin:/milvus/bin:/opt/bitnami/etcd/bin:/opt/bitnami/elasticsearch/bin:/opt/bitnami/java/bin:/home/user/.local/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    JAVA_HOME=/opt/bitnami/java \
    ES_JAVA_HOME=/opt/bitnami/java \
    APP_PORT=7860 \
    DATA_DIR=/data/coze \
    COZE_APP_DIR=/app \
    COZE_WEB_DIR=/opt/coze-web \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

USER root

RUN install_packages \
      bash \
      ca-certificates \
      curl \
      file \
      jq \
      libaio1 \
      libgomp1 \
      libopenblas0 \
      mariadb-client \
      mariadb-server \
      musl \
      nats-server \
      netcat-openbsd \
      nginx \
      procps \
      python3 \
      redis-server \
      supervisor \
      tini \
      tzdata \
      unzip \
      xz-utils \
    && update-ca-certificates

RUN ln -sf /lib/ld-musl-x86_64.so.1 /lib/libc.musl-x86_64.so.1

COPY --from=etcd /opt/bitnami/etcd /opt/bitnami/etcd
COPY --from=milvus /milvus /milvus

RUN set -eux; \
    verify_sha256() { \
      expected="$1"; \
      path="$2"; \
      if [ -n "$expected" ]; then \
        echo "$expected  $path" | sha256sum -c -; \
      else \
        echo "[build] checksum not set for $path; development build only"; \
      fi; \
    }; \
    if ! command -v deno >/dev/null 2>&1; then \
      arch="${TARGETARCH:-amd64}"; \
      case "$arch" in \
        amd64) deno_arch="x86_64-unknown-linux-gnu"; deno_sha="$DENO_SHA256_AMD64" ;; \
        arm64) deno_arch="aarch64-unknown-linux-gnu"; deno_sha="$DENO_SHA256_ARM64" ;; \
        *) echo "Unsupported TARGETARCH=$arch for Deno download" >&2; exit 1 ;; \
      esac; \
      curl -fsSL "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${deno_arch}.zip" -o /tmp/deno.zip; \
      verify_sha256 "$deno_sha" /tmp/deno.zip; \
      unzip -q /tmp/deno.zip -d /usr/local/bin; \
      rm -f /tmp/deno.zip; \
      chmod +x /usr/local/bin/deno; \
    fi

# Atlas CLI is used by Coze's official MySQL bootstrap flow. Keep it optional but available.
RUN set -eux; \
    verify_sha256() { \
      expected="$1"; \
      path="$2"; \
      if [ -n "$expected" ]; then \
        echo "$expected  $path" | sha256sum -c -; \
      else \
        echo "[build] checksum not set for $path; development build only"; \
      fi; \
    }; \
    if [ "$INSTALL_ATLAS" = "true" ]; then \
      curl -fsSL "$ATLAS_INSTALL_URL" -o /tmp/atlas-install.sh; \
      verify_sha256 "$ATLAS_INSTALL_SHA256" /tmp/atlas-install.sh; \
      sh /tmp/atlas-install.sh -y --community || true; \
      rm -f /tmp/atlas-install.sh; \
      if [ -x /root/.local/bin/atlas ]; then cp /root/.local/bin/atlas /usr/local/bin/atlas; fi; \
    fi

# MinIO fallback is included because Milvus and Coze both expect object storage.
RUN set -eux; \
    verify_sha256() { \
      expected="$1"; \
      path="$2"; \
      if [ -n "$expected" ]; then \
        echo "$expected  $path" | sha256sum -c -; \
      else \
        echo "[build] checksum not set for $path; development build only"; \
      fi; \
    }; \
    arch="${TARGETARCH:-amd64}"; \
    case "$arch" in \
      amd64) minio_arch="amd64"; minio_sha="$MINIO_SHA256_AMD64"; mc_sha="$MC_SHA256_AMD64" ;; \
      arm64) minio_arch="arm64"; minio_sha="$MINIO_SHA256_ARM64"; mc_sha="$MC_SHA256_ARM64" ;; \
      *) echo "Unsupported TARGETARCH=$arch for MinIO download" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://dl.min.io/server/minio/release/linux-${minio_arch}/minio" -o /usr/local/bin/minio; \
    curl -fsSL "https://dl.min.io/client/mc/release/linux-${minio_arch}/mc" -o /usr/local/bin/mc; \
    verify_sha256 "$minio_sha" /usr/local/bin/minio; \
    verify_sha256 "$mc_sha" /usr/local/bin/mc; \
    chmod +x /usr/local/bin/minio /usr/local/bin/mc

RUN set -eux; \
    getent group user >/dev/null || groupadd -g 1000 user || groupadd user; \
    id -u user >/dev/null 2>&1 || useradd -m -u 1000 -g user -s /bin/bash user || useradd -m -g user -s /bin/bash user; \
    mkdir -p \
      /bitnami/elasticsearch/data \
      /bitnami/etcd \
      /data/coze \
      /data/coze/elasticsearch \
      /data/coze/etcd \
      /data/coze/milvus \
      /opt/coze-hfs/bin \
      /opt/coze-hfs/conf \
      /opt/coze-hfs/elasticsearch/es_index_schema \
      /opt/coze/bootstrap \
      /opt/coze-web \
      /run/nginx \
      /var/lib/milvus \
      /var/lib/nginx/tmp \
      /var/log/nginx; \
    chown -R user:user /data /opt/coze-hfs /opt/coze /opt/coze-web /run/nginx /var/lib/nginx /var/log/nginx /home/user

COPY --from=coze-server /app /app
COPY --from=coze-web /usr/share/nginx/html/ /opt/coze-web/

# Fetch bootstrap/config files corresponding to the selected Coze git tag.
RUN set -eux; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/volumes/mysql/schema.sql" -o /opt/coze/bootstrap/schema.sql; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/atlas/opencoze_latest_schema.hcl" -o /opt/coze/bootstrap/opencoze_latest_schema.hcl; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/volumes/elasticsearch/elasticsearch.yml" -o /opt/coze-hfs/elasticsearch/elasticsearch.yml; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/volumes/elasticsearch/analysis-smartcn.zip" -o /opt/coze-hfs/elasticsearch/analysis-smartcn.zip; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/volumes/elasticsearch/es_index_schema/coze_resource.index-template.json" -o /opt/coze-hfs/elasticsearch/es_index_schema/coze_resource.index-template.json; \
    curl -fsSL "https://raw.githubusercontent.com/coze-dev/coze-studio/${COZE_GIT_REF}/docker/volumes/elasticsearch/es_index_schema/project_draft.index-template.json" -o /opt/coze-hfs/elasticsearch/es_index_schema/project_draft.index-template.json; \
    sed -i 's/utf8mb4_0900_ai_ci/utf8mb4_unicode_ci/g' /opt/coze/bootstrap/schema.sql /opt/coze/bootstrap/opencoze_latest_schema.hcl; \
    cp /opt/coze-hfs/elasticsearch/elasticsearch.yml /opt/bitnami/elasticsearch/config/my_elasticsearch.yml; \
    chown -R user:user /app /opt/coze /opt/coze-web /opt/coze-hfs

COPY hfs/bin/ /opt/coze-hfs/bin/
COPY hfs/conf/ /opt/coze-hfs/conf/

RUN chmod +x /opt/coze-hfs/bin/*.sh \
    && elasticsearch-plugin install --batch file:///opt/coze-hfs/elasticsearch/analysis-smartcn.zip \
    && LD_LIBRARY_PATH=/milvus/lib ldd /milvus/bin/milvus > /tmp/milvus.ldd \
    && cat /tmp/milvus.ldd \
    && ! grep -q "not found" /tmp/milvus.ldd \
    && file /app/opencoze \
    && ldd /app/opencoze > /tmp/opencoze.ldd \
    && cat /tmp/opencoze.ldd \
    && ! grep -q "not found" /tmp/opencoze.ldd \
    && test -x /usr/bin/tini \
    && test -x /usr/bin/python3 \
    && test -x /usr/sbin/nats-server \
    && chown -R user:user /opt/coze-hfs /app /opt/coze /opt/coze-web /data/coze

WORKDIR /app

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=5 \
  CMD /opt/coze-hfs/bin/healthcheck.sh

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/coze-hfs/bin/entrypoint.sh"]
