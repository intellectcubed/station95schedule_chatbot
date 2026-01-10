# Docker Configuration Files

This directory contains Docker-related configuration files for the GroupMe poller.

## Files

- **`crontab`** - Cron schedule configuration (runs every 10 minutes)
- **`entrypoint.sh`** - Container startup script that validates configuration and starts cron

## Modifying the Cron Schedule

To change the polling frequency, edit `crontab`:

```cron
# Current: Every 10 minutes
*/10 * * * * cd /app && /usr/local/bin/python -m src.station95chatbot.poll_messages >> /app/logs/cron.log 2>&1

# Every 5 minutes
*/5 * * * * cd /app && /usr/local/bin/python -m src.station95chatbot.poll_messages >> /app/logs/cron.log 2>&1

# Every 2 minutes
*/2 * * * * cd /app && /usr/local/bin/python -m src.station95chatbot.poll_messages >> /app/logs/cron.log 2>&1
```

After editing, rebuild the Docker image:
```bash
docker-compose up -d --build
```

## Cron Schedule Format

```
* * * * * command
│ │ │ │ │
│ │ │ │ └─── Day of week (0-7, 0 and 7 are Sunday)
│ │ │ └───── Month (1-12)
│ │ └─────── Day of month (1-31)
│ └───────── Hour (0-23)
└─────────── Minute (0-59)
```

Examples:
- `*/5 * * * *` - Every 5 minutes
- `0 * * * *` - Every hour at :00
- `30 9 * * *` - Every day at 9:30 AM
- `0 */2 * * *` - Every 2 hours
- `0 9-17 * * 1-5` - Every hour from 9 AM to 5 PM, Monday through Friday
