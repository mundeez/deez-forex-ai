# =============================================================================
# deez-forex-ai Frontend Dockerfile
# Multi-stage build: build in Node, serve with minimal runtime.
# =============================================================================

# Stage 1: Build
FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies (cached layer if package.json unchanged)
COPY package.json package-lock.json* ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# Stage 2: Production
FROM node:20-alpine

WORKDIR /app

# Install serve for static file hosting
RUN npm install -g serve

# Create non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Copy built Next.js output
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Change ownership
RUN chown -R appuser:appgroup /app
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3000/ || exit 1

EXPOSE 3000

CMD ["serve", "-s", ".", "-l", "3000"]
