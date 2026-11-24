FROM node:22-alpine AS frontend-build
WORKDIR /web
ARG VITE_FIREBASE_CONFIG_API_KEY
ENV VITE_FIREBASE_CONFIG_API_KEY=${VITE_FIREBASE_CONFIG_API_KEY}
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.11-slim

# FFmpeg is required for:
# - extracting audio from MP4
# - burning subtitles into video
RUN apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY backend ./backend
COPY frontend ./frontend
COPY static ./static
COPY --from=frontend-build /web/dist ./web/dist

# Runtime dirs (so the backend can write files)
RUN mkdir -p uploads output library

ENV PYTHONUNBUFFERED=1

# Cloud Run injects PORT. Default to 8080 for local parity.
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT}"]
