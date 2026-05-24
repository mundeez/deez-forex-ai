# =============================================================================
# deez-forex-ai Frontend Dockerfile
# Single-stage build that supports both production and development.
# Production uses CMD ["npm", "start"]; dev overrides to "npx next dev".
# =============================================================================

FROM node:20-alpine

WORKDIR /app

# Install dependencies (including devDependencies for build)
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

EXPOSE 3000

CMD ["npm", "start"]
