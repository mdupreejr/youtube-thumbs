ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python, pip, and curl (for health checks)
RUN apk add --no-cache \
    python3 \
    py3-pip \
    curl \
    && ln -sf python3 /usr/bin/python

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

# Copy all application files
COPY *.py .

# Copy startup script
COPY run.sh .
RUN chmod +x run.sh

# Expose port (although host_network=true means this is mostly for documentation)
EXPOSE 21812

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:21812/health || exit 1

# Run the startup script
CMD [ "/app/run.sh" ]
