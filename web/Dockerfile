# ── AEGIS Web Dashboard & SOC Surveillance Interface ────────────────────────
FROM node:20-alpine

WORKDIR /app

# Install curl for healthcheck probe
RUN apk add --no-cache curl

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy application source
COPY . .

ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:3000/api/health || curl -f http://localhost:3000 || exit 1

CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0"]
