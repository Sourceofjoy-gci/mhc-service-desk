# syntax=docker/dockerfile:1.7
# =============================================================================
# MHC e-Ticketing — production frontend image
# Multi-stage: dev stage installs deps (used by docker-compose dev profile),
# production target builds the static bundle and copies it into the
# nginx-served volume.
# =============================================================================

# ---- dev stage: used by docker-compose dev profile (npm run dev) -------
FROM node:22.14.0-alpine AS dev
WORKDIR /app
COPY package.json package-lock.json ./
ARG NPM_CONFIG_STRICT_SSL=true
RUN npm_config_strict_ssl=$NPM_CONFIG_STRICT_SSL npm install --no-audit --no-fund --legacy-peer-deps
RUN sha256sum package-lock.json | cut -d ' ' -f 1 > node_modules/.mhc-package-lock-hash
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

# ---- production target -----------------------------------------------
FROM node:22.14.0-alpine AS production
WORKDIR /app
ENV NODE_ENV=production

COPY package.json package-lock.json ./
ARG NPM_CONFIG_STRICT_SSL=true
RUN npm_config_strict_ssl=$NPM_CONFIG_STRICT_SSL npm install --no-audit --no-fund --legacy-peer-deps

COPY . .

# Build arguments: turn off the dev-bypass in production builds.
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_KEYCLOAK_URL=https://keycloak.local
ARG VITE_KEYCLOAK_REALM=mhc
ARG VITE_KEYCLOAK_CLIENT_ID=mhc-frontend
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_KEYCLOAK_URL=$VITE_KEYCLOAK_URL \
    VITE_KEYCLOAK_REALM=$VITE_KEYCLOAK_REALM \
    VITE_KEYCLOAK_CLIENT_ID=$VITE_KEYCLOAK_CLIENT_ID \
    VITE_DEV_AUTH=

RUN npm run build

# The output goes into the `frontend-static` named volume, which the
# Nginx service mounts at /usr/share/nginx/html. No app server runs.
CMD ["sh", "-c", "cp -r dist/* /output/ && echo 'frontend bundle copied to /output'"]
