# ============================================================
# WebReel Frontend - Production Build
# Multi-stage: Node (build) -> Nginx (serve)
# ============================================================

# --- Stage 1: Build ---
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies first (layer cache)
COPY package.json ./
RUN npm install

# Copy source code
COPY . .

# Build arg for API URL (injected at build time)
ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}

# Build arg for Google OAuth Client ID
ARG VITE_GOOGLE_CLIENT_ID=
ENV VITE_GOOGLE_CLIENT_ID=${VITE_GOOGLE_CLIENT_ID}

# Build production bundle
RUN npm run build

# --- Stage 2: Serve with Nginx ---
FROM nginx:1.27-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
