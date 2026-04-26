# Stage 1: Build frontend with official Node image
FROM node:18-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --omit=dev
COPY frontend/ .
ENV VITE_API_BASE=""
RUN npm run build

# Stage 2: Python runtime (no Node bloat in production)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Pull the built frontend from stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info"]
