#!/bin/sh
# Frontend container entrypoint.
#
# Generates the runtime config.js (window.TRANSLATOR_CONFIG) from
# BACKEND_HOST / BACKEND_USE_TLS, then hands over to the official nginx image
# entrypoint (which runs nginx and its template processing).
set -eu

: "${BACKEND_HOST:=}"
: "${BACKEND_USE_TLS:=false}"

# Only these two variables are substituted so nginx $vars are never touched.
envsubst '${BACKEND_HOST} ${BACKEND_USE_TLS}' \
    < /etc/nginx/config.js.template \
    > /usr/share/nginx/html/config.js

echo "[frontend] BACKEND_HOST='${BACKEND_HOST}' BACKEND_USE_TLS='${BACKEND_USE_TLS}'"

exec /docker-entrypoint.sh "$@"
