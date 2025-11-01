#!/bin/bash
# Wrapper script to run app.py with full error capture

set -e

echo "=== Starting Python app with full error capture ===" >&2
echo "=== Python version: $(python3 --version) ===" >&2
echo "=== Current directory: $(pwd) ===" >&2
echo "=== Files in /app: $(ls -la /app/*.py 2>&1 | head -5) ===" >&2

# Run Python with unbuffered output and capture exit code
echo "=== Launching python3 -u app.py ===" >&2
python3 -u app.py 2>&1 || {
    EXIT_CODE=$?
    echo "=== Python crashed or exited with code: $EXIT_CODE ===" >&2
    exit $EXIT_CODE
}

echo "=== Python process completed normally ===" >&2
