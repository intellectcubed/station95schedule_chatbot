#!/bin/bash
set -e

echo "=========================================="
echo "Station 95 GroupMe Chatbot - Poller Mode"
echo "=========================================="
echo ""
echo "Starting at: $(date)"
echo "Python version: $(python --version)"
echo "Working directory: $(pwd)"
echo ""

# Validate required environment variables
REQUIRED_VARS=(
    "GROUPME_API_TOKEN"
    "GROUPME_GROUP_ID"
    "GROUPME_BOT_ID"
)

# Check AI provider requirements
if [ "$AI_PROVIDER" = "openai" ] && [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY is required when AI_PROVIDER=openai"
    exit 1
fi

if [ "$AI_PROVIDER" = "anthropic" ] && [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is required when AI_PROVIDER=anthropic"
    exit 1
fi

echo "Environment Check:"
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo "  ✗ $var is not set"
        exit 1
    else
        # Show first few characters only for security
        value="${!var}"
        masked="${value:0:6}***"
        echo "  ✓ $var is set ($masked)"
    fi
done

echo ""
echo "Configuration:"
echo "  AI Provider: ${AI_PROVIDER:-openai}"
echo "  AI Mode: ${AI_MODE:-simple}"
echo "  Log Level: ${LOG_LEVEL:-INFO}"
echo "  Roster File: ${ROSTER_FILE_PATH:-data/roster.json}"
echo ""

# Create necessary directories
mkdir -p /app/data /app/logs

# Test the configuration by running one poll
echo "=========================================="
echo "Running initial poll test..."
echo "=========================================="
cd /app && python -m src.station95chatbot.poll_messages

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ Initial poll successful!"
else
    echo ""
    echo "✗ Initial poll failed - check configuration"
    exit 1
fi

echo ""
echo "=========================================="
echo "Starting cron scheduler..."
echo "=========================================="
echo "Schedule: Every 10 minutes (*/10 * * * *)"
echo "Logs: /app/logs/cron.log"
echo ""
echo "Container is now running. Press Ctrl+C to stop."
echo "=========================================="
echo ""

# Execute the main command (passed as CMD in Dockerfile)
exec "$@"
