FROM rust:1-slim AS builder

WORKDIR /app
COPY rust-backend/Cargo.toml rust-backend/Cargo.lock ./rust-backend/
COPY rust-backend/src ./rust-backend/src

WORKDIR /app/rust-backend
RUN cargo build --release --locked

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 dataos

WORKDIR /app
COPY --from=builder /app/rust-backend/target/release/dataos-backend /usr/local/bin/dataos-backend

ENV DATAOS_DB_PATH=/app/data/dataos.db \
    DATAOS_BLOB_DIR=/app/data/blobs \
    DATAOS_ENV=production \
    DATAOS_ALLOW_PYTHON_COMPUTE=false

RUN mkdir -p /app/data && chown -R dataos:dataos /app/data
USER dataos
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["dataos-backend"]
