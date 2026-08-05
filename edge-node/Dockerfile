# Stage 1: Build the binary
FROM rust:1.75-slim as builder

WORKDIR /usr/src/edge-node

RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*

COPY Cargo.toml ./
# Build dummy main to cache dependencies
RUN mkdir src && echo "fn main() {}" > src/main.rs && cargo build --release && rm -rf src

COPY src ./src
RUN cargo build --release

# Stage 2: Minimal Runtime Image
FROM debian:bookworm-slim

WORKDIR /app

RUN apt-get update && apt-get install -y ca-certificates libssl-dev && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/src/edge-node/target/release/edge-node /usr/local/bin/edge-node

EXPOSE 8080

ENV RUST_LOG=info \
    PORT=8080 \
    MQTT_HOST=mosquitto \
    MQTT_PORT=1883 \
    MQTT_TOPIC=safety/blackbox/dump

CMD ["edge-node"]
