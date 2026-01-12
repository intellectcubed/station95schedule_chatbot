#!/bin/bash
# REPL script for continuously polling GroupMe messages
# Runs poll.sh in a loop with configurable sleep interval

# Get the script's directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Default sleep interval (in seconds)
SLEEP_INTERVAL=${1:-20}

echo "Starting poller REPL with ${SLEEP_INTERVAL} second interval"
echo "Press Ctrl+C to stop"
echo "---"

# Infinite loop
while true; do
    # Run the poll script
    "$SCRIPT_DIR/poll.sh"

    # Capture exit code
    EXIT_CODE=$?

    # Display timestamp and exit code
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Poll completed with exit code: $EXIT_CODE"

    # Sleep for the configured interval
    echo "Sleeping for ${SLEEP_INTERVAL} seconds..."
    sleep "$SLEEP_INTERVAL"
    echo "---"
done
