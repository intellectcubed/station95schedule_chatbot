# station95schedule_chatbot

## Overview
A chatbot that polls GroupMe messages and responds to scheduling queries.

### Manual Testing

### Model testing
In a browser, open the below file and paste in the API key:
file:///Users/george.nowakowski/Projects/python/ems/station95schedule_chatbot/diagnostics/index.html

Features:
- Test prompts against OpenAI models (GPT-4, GPT-4 Turbo, GPT-3.5 Turbo, GPT-4o, GPT-4o-mini)
- Configure temperature and other parameters
- **Tool/Function Calling**: Enable any combination of the following tools defined in `src/tools.py`:
  - `get_schedule`: Fetch schedule from calendar service for a date range
  - `check_squad_scheduled`: Check if a specific squad is scheduled for a shift
  - `count_active_crews`: Count active crews during a shift
  - `parse_time_reference`: Parse natural language time references
- View token usage and response time metrics
- See tool calls made by the model in the response

---

#### Single Poll
To run a single poll of GroupMe messages:
```bash
./scripts/poll.sh
```

This script will:
- Activate the virtual environment (if present)
- Run the polling module once
- Exit with the appropriate exit code

#### Continuous Polling (REPL Mode)
To continuously poll GroupMe messages with a configurable interval:
```bash
./scripts/poller_repl.sh [SECONDS]
```

Parameters:
- `SECONDS` (optional): Time to sleep between polls. Default is 20 seconds.

Examples:
```bash
# Poll every 20 seconds (default)
./scripts/poller_repl.sh

# Poll every 60 seconds
./scripts/poller_repl.sh 60

# Poll every 5 seconds
./scripts/poller_repl.sh 5
```

The REPL will display timestamps and exit codes for each poll cycle. Press Ctrl+C to stop the continuous polling.
