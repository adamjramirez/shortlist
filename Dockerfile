# Stage 1: Build Next.js
FROM node:20-alpine AS web-builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# Stage 2: Production
FROM python:3.13-slim
WORKDIR /app

# Node.js + supervisor + curl
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl supervisor && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Backend
COPY shortlist/ /app/shortlist/
COPY alembic/ /app/alembic/
COPY alembic.ini /app/

# Next.js standalone build
COPY --from=web-builder /app/web/.next/standalone /app/web
COPY --from=web-builder /app/web/.next/static /app/web/.next/static
COPY --from=web-builder /app/web/public /app/web/public

COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s \
  CMD curl -f http://localhost:3000/api/health || exit 1

CMD ["/app/start.sh"]
