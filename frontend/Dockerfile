FROM node:22-slim AS build

ENV NEXT_TELEMETRY_DISABLED=1 \
    CI=1

WORKDIR /app

# pnpm, in the version package.json names.
RUN corepack enable

# Dependencies first, so this layer is reused until the lock file changes.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .
RUN pnpm build


FROM node:22-slim

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# The server and only what it needs to run: no package manager, no sources.
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

# The image's own unprivileged user.
USER node
EXPOSE 3000

CMD ["node", "server.js"]
