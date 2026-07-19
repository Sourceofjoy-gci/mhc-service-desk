# syntax=docker/dockerfile:1.7
# =============================================================================
# MHC e-Ticketing — frontend image (dev profile; production uses static build)
# =============================================================================
FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --no-audit --no-fund --legacy-peer-deps
ENV VITE_DEV_AUTH=1

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
