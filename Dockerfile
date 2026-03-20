# =============================================================================
# Stage 1: Build the frontend
# =============================================================================
FROM node:20-alpine AS frontend-build

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# =============================================================================
# Stage 2: Runtime — Python + Nginx + supervisord
# =============================================================================
FROM python:3.12-slim

# Install nginx and supervisord
RUN apt-get update && \
    apt-get install -y --no-install-recommends nginx supervisor && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
WORKDIR /app
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/

# Copy frontend build output to nginx html root
COPY --from=frontend-build /build/dist/ /usr/share/nginx/html/

# Remove default nginx config, add ours
RUN rm -f /etc/nginx/sites-enabled/default /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/dashboard.conf

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/dashboard.conf

RUN mkdir -p /app/data /app/private

EXPOSE 80

CMD ["supervisord", "-c", "/etc/supervisor/conf.d/dashboard.conf"]
