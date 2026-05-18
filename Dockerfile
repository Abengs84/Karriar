# Build frontend
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Backend + serve frontend
FROM python:3.12-slim
WORKDIR /app

# No extra system deps required for reportlab on slim

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Finska IP-intervall (landskod FI)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && mkdir -p /app/backend/data \
    && curl -fsSL -o /app/backend/data/fi-ipv4.cidr \
       "https://raw.githubusercontent.com/ipverse/rir-ip/master/country/fi/ipv4-aggregated.txt" \
    && curl -fsSL -o /app/backend/data/fi-ipv6.cidr \
       "https://raw.githubusercontent.com/ipverse/rir-ip/master/country/fi/ipv6-aggregated.txt" \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
COPY img/ ./img/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

ENV DATABASE_URL=sqlite:///./data/karriar.db
# Sätt KARRIAR_PASSWORD vid körning (docker-compose / .env)
ENV PYTHONPATH=/app/backend
ENV FRONTEND_DIR=/app/frontend/dist
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

WORKDIR /app/backend
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
