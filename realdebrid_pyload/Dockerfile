# Home Assistant passes the right image for your CPU from build.yaml.
# The default below is only used if nothing is passed (64-bit Intel/AMD).
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.21
FROM ${BUILD_FROM}

RUN apk add --no-cache python3 py3-requests

COPY app /app

CMD [ "python3", "-u", "/app/main.py" ]
