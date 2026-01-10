# Docker Deployment for GroupMe Poller

This guide covers deploying the GroupMe poller as a Docker container with automatic cron scheduling.

## Quick Start

1. **Copy environment template**
   ```bash
   cp .env.docker.example .env
   ```

2. **Edit `.env` with your credentials**
   ```bash
   nano .env  # or use your preferred editor
   ```

3. **Ensure roster file exists**
   ```bash
   # Make sure data/roster.json exists and is configured
   ls -la data/roster.json
   ```

4. **Build and run with Docker Compose**
   ```bash
   docker-compose up -d
   ```

5. **Check logs**
   ```bash
   docker-compose logs -f
   ```

## What Gets Deployed

The Docker container includes:
- Python 3.11 runtime
- All required dependencies
- Cron daemon configured to poll every 10 minutes
- Automatic state management (last message ID tracking)
- Persistent volumes for data and logs

## Directory Structure

```
station95chatbot/
├── Dockerfile                  # Main Docker image definition
├── docker-compose.yml          # Docker Compose orchestration
├── .env                        # Your environment variables (create from .env.docker.example)
├── .env.docker.example         # Template for environment variables
├── docker/
│   ├── crontab                 # Cron schedule configuration
│   └── entrypoint.sh           # Container startup script
├── data/
│   ├── roster.json             # Roster configuration (required)
│   └── last_message_id.txt     # State file (auto-created)
└── logs/
    ├── cron.log                # Cron execution logs
    └── station95chatbot.log    # Application logs
```

## Configuration

### Environment Variables

All configuration is done via environment variables in `.env`:

**Required:**
- `GROUPME_API_TOKEN` - Your GroupMe API access token
- `GROUPME_GROUP_ID` - The GroupMe group ID to poll
- `GROUPME_BOT_ID` - Your GroupMe bot ID (for sending messages)
- `AI_PROVIDER` - Either "openai" or "anthropic"
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` - Depending on provider
- `CALENDAR_SERVICE_URL` - Your calendar service endpoint

**Optional:**
- `AI_MODE` - "simple" (default) or "agentic"
- `CONFIDENCE_THRESHOLD` - Minimum confidence score (default: 70)
- `LOG_LEVEL` - DEBUG, INFO, WARNING, ERROR (default: INFO)
- `ROSTER_FILE_PATH` - Path to roster file (default: data/roster.json)

### Cron Schedule

By default, the poller runs every 10 minutes. To change this:

1. Edit `docker/crontab`:
   ```cron
   # Every 5 minutes
   */5 * * * * cd /app && /usr/local/bin/python -m src.station95chatbot.poll_messages >> /app/logs/cron.log 2>&1

   # Every 2 minutes
   */2 * * * * cd /app && /usr/local/bin/python -m src.station95chatbot.poll_messages >> /app/logs/cron.log 2>&1

   # Every hour
   0 * * * * cd /app && /usr/local/bin/python -m src.station95chatbot.poll_messages >> /app/logs/cron.log 2>&1
   ```

2. Rebuild the container:
   ```bash
   docker-compose down
   docker-compose up -d --build
   ```

## Docker Commands

### Using Docker Compose (Recommended)

```bash
# Start the poller
docker-compose up -d

# View logs (real-time)
docker-compose logs -f

# View cron logs specifically
docker-compose exec groupme-poller tail -f /app/logs/cron.log

# Stop the poller
docker-compose down

# Restart the poller
docker-compose restart

# Rebuild after code changes
docker-compose up -d --build

# View container status
docker-compose ps
```

### Using Docker CLI

```bash
# Build the image
docker build -t station95-poller .

# Run the container
docker run -d \
  --name station95-poller \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  station95-poller

# View logs
docker logs -f station95-poller

# Stop the container
docker stop station95-poller

# Remove the container
docker rm station95-poller
```

## Volumes and Persistence

The container uses two persistent volumes:

1. **`/app/data`** - Application data
   - `last_message_id.txt` - Tracks the last processed message
   - `roster.json` - Member roster configuration

2. **`/app/logs`** - Log files
   - `cron.log` - Cron execution logs
   - `station95chatbot.log` - Application logs

These volumes are mapped to your local filesystem, so data persists even if the container is stopped or removed.

## Monitoring and Debugging

### View Recent Polls

```bash
# View cron execution logs
docker-compose exec groupme-poller tail -n 50 /app/logs/cron.log

# View application logs
docker-compose exec groupme-poller tail -n 50 /app/logs/station95chatbot.log

# Follow logs in real-time
docker-compose exec groupme-poller tail -f /app/logs/cron.log
```

### Check Cron Status

```bash
# Verify cron is running
docker-compose exec groupme-poller pgrep cron

# View installed crontab
docker-compose exec groupme-poller crontab -l

# Check when next poll will run
docker-compose exec groupme-poller grep CRON /var/log/syslog | tail -n 5
```

### Manual Poll Trigger

```bash
# Run a poll manually (without waiting for cron)
docker-compose exec groupme-poller python -m src.station95chatbot.poll_messages
```

### Access Container Shell

```bash
# Open a shell in the running container
docker-compose exec groupme-poller bash

# Inside the container, you can:
python -m src.station95chatbot.poll_messages  # Manual poll
cat /app/data/last_message_id.txt             # Check state
ls -la /app/logs/                              # View logs
```

## Troubleshooting

### Container Exits Immediately

Check logs for configuration errors:
```bash
docker-compose logs
```

Common issues:
- Missing required environment variables
- Invalid API keys
- Roster file not found

### No Messages Being Processed

1. **Check if cron is running:**
   ```bash
   docker-compose exec groupme-poller pgrep cron
   ```

2. **View cron logs:**
   ```bash
   docker-compose exec groupme-poller tail -f /app/logs/cron.log
   ```

3. **Test manual poll:**
   ```bash
   docker-compose exec groupme-poller python -m src.station95chatbot.poll_messages
   ```

4. **Check state file:**
   ```bash
   cat data/last_message_id.txt
   # Delete to reprocess messages:
   rm data/last_message_id.txt
   ```

### Reset State

To reprocess messages or start fresh:
```bash
# Stop container
docker-compose down

# Remove state file
rm data/last_message_id.txt

# Restart container
docker-compose up -d
```

### View Environment Variables

```bash
# Check what environment variables are set
docker-compose exec groupme-poller env | grep -E "GROUPME|AI|CALENDAR"
```

## Production Deployment

### Resource Limits

The `docker-compose.yml` includes resource limits:
- CPU: 0.5 cores max, 0.1 cores reserved
- Memory: 512MB max, 128MB reserved

Adjust based on your needs:
```yaml
deploy:
  resources:
    limits:
      cpus: '1.0'
      memory: 1G
```

### Auto-Restart

The container is configured to restart automatically:
```yaml
restart: unless-stopped
```

Options:
- `no` - Never restart
- `always` - Always restart
- `unless-stopped` - Restart unless manually stopped
- `on-failure` - Restart only on error

### Health Checks

The container includes a health check that monitors cron:
```bash
# Check container health
docker-compose ps

# View health check logs
docker inspect --format='{{json .State.Health}}' station95-groupme-poller | jq
```

### Running on Server

1. **Install Docker and Docker Compose:**
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo apt-get install docker-compose-plugin
   ```

2. **Clone repository:**
   ```bash
   git clone <your-repo-url>
   cd station95chatbot
   ```

3. **Configure environment:**
   ```bash
   cp .env.docker.example .env
   nano .env  # Add your credentials
   ```

4. **Start service:**
   ```bash
   docker-compose up -d
   ```

5. **Enable on boot:**
   Docker Compose with `restart: unless-stopped` will auto-start on server reboot.

### Updating

To update the poller code:
```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose up -d --build
```

## Security Considerations

1. **Environment Variables**
   - Never commit `.env` to git (already in `.gitignore`)
   - Use strong, unique API keys
   - Rotate credentials periodically

2. **File Permissions**
   ```bash
   chmod 600 .env
   chmod 644 data/roster.json
   ```

3. **Network Isolation**
   The container only needs outbound internet access (to GroupMe API and Calendar service). No inbound ports are required for polling mode.

4. **Container Updates**
   Keep base image updated:
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

## Comparison: Docker vs Manual Deployment

| Feature | Docker | Manual |
|---------|--------|--------|
| Setup complexity | Medium | Low |
| Isolation | Full isolation | Shares system Python |
| Portability | Runs anywhere | System-dependent |
| Updates | Rebuild image | Update files |
| Resource control | Built-in limits | Manual configuration |
| Auto-restart | Built-in | Systemd service needed |
| Best for | Production, cloud | Development, simple setups |
