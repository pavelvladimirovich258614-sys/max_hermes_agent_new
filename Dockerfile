# MAX Hermes Agent — Docker (experimental)
# This Dockerfile is for isolated testing only.
# For production, install Hermes Agent natively and use this plugin.

FROM python:3.11-slim

WORKDIR /app

# Copy plugin files
COPY plugin/ /app/plugin/
COPY scripts/ /app/scripts/
COPY examples/ /app/examples/

# Note: Hermes Agent must be installed separately.
# This Docker image only contains the MAX plugin files.
# To use, mount your Hermes home directory:
#   docker run -v ~/.hermes:/root/.hermes ...

RUN chmod +x /app/scripts/*.sh 2>/dev/null || true

CMD ["echo", "See docs/DOCKER.md for usage instructions"]
