# Build stage: dependencies installed in a virtualenv, copied as a whole.
FROM python:3.12-slim AS build
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# Requirements first: this layer is rebuilt only when dependencies change,
# not on every code change.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Runtime stage: no pip, no build cache, non-root user.
FROM python:3.12-slim
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION \
    PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# Base images lag behind Debian security fixes: apply them at build time.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY app ./app
USER 10001:10001
EXPOSE 8000
# Access logs come from the app middleware, in JSON (uvicorn's are plain text).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
