# Unprivileged variant: runs as UID 101 and listens on 8080.
FROM nginxinc/nginx-unprivileged:1.31-alpine

# Base images lag behind Alpine security fixes: apply them at build time.
USER root
RUN apk upgrade --no-cache
USER 101

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 8080
