FROM node:24-bookworm-slim AS build

# Docker context has no .git. Pin the 7-char hash the client artifacts embed.
ARG DSH_CLIENT_COMMIT_HASH=058263b
ENV DSH_CLIENT_COMMIT_HASH=$DSH_CLIENT_COMMIT_HASH

RUN corepack enable && corepack prepare pnpm@11.7.0 --activate
WORKDIR /workspace
COPY . .
# `pnpm dsh` runs Host from source via tsx. `dsh --profile web` still needs
# built `packages/*/lib/client.js` and `apps/web/dist` or it exits with
# MissingClientBundleError. `build:web-image` is `pnpm run build` without
# test typecheck (`tsc --noCheck`) and with `tsdown --config-loader tsx`.
RUN pnpm install --frozen-lockfile \
 && pnpm run build:web-image

FROM node:24-bookworm-slim
ARG DSH_CLIENT_COMMIT_HASH=058263b
RUN corepack enable && corepack prepare pnpm@11.7.0 --activate
WORKDIR /workspace
COPY --from=build /workspace .
ENV DSH_HOME=/var/lib/dsh \
    HOME=/var/lib/dsh-home \
    DSH_CLIENT_COMMIT_HASH=$DSH_CLIENT_COMMIT_HASH
RUN mkdir -p /var/lib/dsh /var/lib/dsh-home
EXPOSE 3080
# Binds 127.0.0.1:3080 on purpose. The K8s sidecar nginx publishes :8080
# and rewrites Host so DeepSeek's loopback trust fence still holds.
CMD ["pnpm", "dsh", "--profile", "web", "--patch", "packages/bundle/video-agent/cordis.patch.yml", "--no-open"]
