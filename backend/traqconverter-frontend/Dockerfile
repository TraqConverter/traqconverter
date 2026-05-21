# syntax=docker/dockerfile:1.6
# ============================================================
# TraqConverter frontend (Next.js 16, standalone output).
#
#   docker build -t traqconverter-frontend .
#   docker run --env NEXT_PUBLIC_API_URL=https://api.example.com \
#              -p 3000:3000 traqconverter-frontend
# ============================================================

# ---- 1. Install dependencies ----
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# ---- 2. Build ----
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---- 3. Runtime — slim image with only the standalone output ----
FROM node:20-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user
RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 --ingroup nodejs nextjs

# Copy only what `next build` with output: 'standalone' produced
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

# `server.js` is the standalone entrypoint Next.js generates.
CMD ["node", "server.js"]
