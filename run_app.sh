#!/bin/bash
# Wrapper script to run app.py with full error capture

set -e

echo "=== Starting Python app with full error capture ===" >&2

# Run Python with unbuffered output and capture exit code
python3 -u app.py 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "=== Python exited with code: $EXIT_CODE ===" >&2
    exit $EXIT_CODE
fi
