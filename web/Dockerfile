# ── AEGIS Web Dashboard & SOC Surveillance Interface ────────────────────────
FROM node:22.23.5-alpine

WORKDIR /app

# Install curl for healthcheck probe
RUN apk add --no-cache curl

# Install dependencies cleanly from lockfile
COPY --chown=node:node package*.json ./
RUN npm ci

# Copy application source
COPY --chown=node:node . .
RUN mkdir -p /app/.next && chown -R node:node /app

ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

USER node
EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fs http://localhost:3000/api/health || curl -fs http://localhost:3000 || exit 1

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
