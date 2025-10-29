ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest
FROM $BUILD_FROM

# Install Python and pip
RUN apk add --no-cache \
    python3 \
    py3-pip \
    && ln -sf python3 /usr/bin/python

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

# Copy all application files
COPY *.py ./

# Copy the database module directory
COPY database/ ./database/

# Copy templates directory for Flask web UI
COPY templates/ ./templates/

# Copy startup script
COPY run.sh .
RUN chmod +x run.sh

# Expose port (although host_network=true means this is mostly for documentation)
EXPOSE 21812

# Run the startup script
CMD [ "/app/run.sh" ]
