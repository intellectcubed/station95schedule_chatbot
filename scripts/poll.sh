#!/bin/bash
# Wrapper script for polling GroupMe messages
# Can be called directly by cron or systemd timer

# Get the script's directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Change to project root (parent of scripts directory)
cd "$SCRIPT_DIR/.."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Run the polling script
python -m src.poll_messages

# Capture exit code
EXIT_CODE=$?

# Exit with same code
exit $EXIT_CODE
