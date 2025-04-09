# Stage 1: Build
FROM python:3.13.2-slim-bookworm AS builder

WORKDIR /app

# Install build dependencies (if needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install --prefix=/install -r requirements.txt

# Copy source code
COPY . .

# Stage 2: Final minimal image
FROM python:3.13.2-slim-bookworm

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local
COPY --from=builder /app /app

CMD ["python", "main.py"]
