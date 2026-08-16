# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build the production React bundle. node_modules never leaves this
# stage.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app

# Install dependencies (lockfile-pinned). Cached until package files change.
COPY package.json package-lock.json ./
RUN npm ci

# Full source, then the production build.
COPY . .
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: serve the built SPA with nginx. The runtime config.js (backend
# endpoint) is generated at container startup -- no rebuild needed to point
# the app at a different server.
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html

# Static nginx site config (WebSocket reverse proxy to the backend service).
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
# Runtime template for window.TRANSLATOR_CONFIG (envsubst at startup).
COPY nginx/config.js.template /etc/nginx/config.js.template

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint-custom.sh
RUN chmod +x /usr/local/bin/docker-entrypoint-custom.sh

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/health >/dev/null || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint-custom.sh"]
CMD ["nginx", "-g", "daemon off;"]
