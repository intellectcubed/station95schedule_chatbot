# Prompt Tester Utility

A simple command-line tool to test LLM prompts without running the full chatbot.

## Features

- ✅ Read prompts from files
- ✅ Merge placeholder values using `{placeholder}` syntax
- ✅ Send to any ChatGPT model
- ✅ Configurable temperature
- ✅ Verbose or JSON output modes
- ✅ API key from environment variable

## Installation

The script uses existing project dependencies (langchain_openai). Ensure your environment is activated:

```bash
source venv/bin/activate  # or your virtualenv path
```

Make sure `OPENAI_API_KEY` is set:

```bash
export OPENAI_API_KEY="sk-..."
```

## Usage

### Full Prompt test: 
```bash
python scripts/prompt_tester.py ai_prompts/system_prompt.md \
      --model gpt-4o-mini \
      --tools \
      --verbose \
      -p "user_message=42 has a crew from 1 - 4am" \
      -p "current_datetime=2026-01-03 21:08:00" \
      -p "sender_name=Kohler" \
      -p "sender_squad=42" \
      -p "current_datetime=2026-01-03 22:33:52" \
      -p "sender_role=Chief" \
      -p "resolved_days=2026-01-03" \
      -p "schedule_state=@data/schedule_saturday.json" --verbose
```

### Basic Examples

**1. Test a simple prompt file (default: gpt-4o-mini, temp=0.3)**
```bash
python scripts/prompt_tester.py scripts/example_prompt.txt \
    -p "date=2026-01-03" \
    -p "time=21:08" \
    -p "sender=Squad 42" \
    -p "message=We need coverage tonight"
```

**2. Use gpt-4o instead of gpt-4o-mini**
```bash
python scripts/prompt_tester.py ai_prompts/IntentDetectionPrompt.md \
    --model gpt-4o \
    -p "message=42 has a crew from 1-4am" \
    -p "current_date=2026-01-03" \
    -p "current_time=21:08:00"
```

**3. Adjust temperature**
```bash
python scripts/prompt_tester.py ai_prompts/system_prompt.txt \
    --temperature 0.7 \
    -p "user_message=We can't make it tonight"
```

**4. Get JSON output**
```bash
python scripts/prompt_tester.py scripts/example_prompt.txt \
    --json \
    -p "message=Squad 35 has coverage"
```

**5. Verbose mode (shows model, prompt, response, and token usage)**
```bash
python scripts/prompt_tester.py scripts/example_prompt.txt \
    --verbose \
    -p "message=Need help for Sunday"
```

### Real-World Example: Test Intent Detection

```bash
python scripts/prompt_tester.py ai_prompts/IntentDetectionPrompt.md \
    --model gpt-4o \
    --temperature 0.1 \
    -p "current_date=2026-01-03" \
    -p "current_day_of_week=Saturday" \
    -p "current_time=21:08:00" \
    -p "day_week_reference=Today: Saturday (2026-01-03)
Tomorrow: Sunday (2026-01-04)" \
    -p "message=42 has a crew from 1-4am"
```

### Command-Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `prompt_file` | Path to prompt file (required) | - |
| `-m, --model` | ChatGPT model to use | `gpt-4o-mini` |
| `-t, --temperature` | Temperature (0.0 - 2.0) | `0.3` |
| `-p, --placeholders` | Placeholder values as `key=value` | - |
| `-v, --verbose` | Show detailed output | False |
| `-j, --json` | Output as JSON | False |

## Placeholder Syntax

Prompts use Python's `.format()` syntax for placeholders:

```
Hello {name}, today is {date}.
```

Provide values via command line:
```bash
python prompt_tester.py prompt.txt \
    -p "name=Alice" \
    -p "date=2026-01-03"
```

**Note:** To use literal braces in your prompt (like in JSON examples), double them: `{{` and `}}`.

## Output Modes

### Default (content only)
```bash
python prompt_tester.py prompt.txt -p "message=test"
```
```
This is the LLM response content only.
```

### Verbose
```bash
python prompt_tester.py prompt.txt -p "message=test" --verbose
```
```
================================================================================
MODEL: gpt-4o-mini
TEMPERATURE: 0.3
================================================================================

PROMPT:
[Full prompt here...]

--------------------------------------------------------------------------------

RESPONSE:
[LLM response here...]

--------------------------------------------------------------------------------
TOKENS: 150 (prompt: 100, completion: 50)
================================================================================
```

### JSON
```bash
python prompt_tester.py prompt.txt -p "message=test" --json
```
```json
{
  "model": "gpt-4o-mini",
  "temperature": 0.3,
  "content": "LLM response here...",
  "usage": {
    "total_tokens": 150,
    "prompt_tokens": 100,
    "completion_tokens": 50
  }
}
```

## Use Cases

### 1. Quick Prompt Testing
Test prompts without running the full chatbot workflow:
```bash
python scripts/prompt_tester.py ai_prompts/IntentDetectionPrompt.md \
    -p "message=We need coverage tonight" \
    -p "current_date=2026-01-03"
```

### 2. Model Comparison
Compare gpt-4o vs gpt-4o-mini responses:
```bash
# Test with gpt-4o-mini
python scripts/prompt_tester.py prompt.txt --model gpt-4o-mini

# Test with gpt-4o
python scripts/prompt_tester.py prompt.txt --model gpt-4o
```

### 3. Temperature Experimentation
Find the right temperature for your use case:
```bash
for temp in 0.1 0.3 0.5 0.7; do
    echo "=== Temperature: $temp ==="
    python scripts/prompt_tester.py prompt.txt --temperature $temp
done
```

### 4. Debugging Date Resolution
Test the operational shift day logic:
```bash
python scripts/prompt_tester.py ai_prompts/IntentDetectionPrompt.md \
    --model gpt-4o \
    -p "current_time=21:08:00" \
    -p "message=42 has a crew from 1-4am" \
    --verbose
```

## Example Prompt File

See `scripts/example_prompt.txt` for a simple example with placeholders.

## Troubleshooting

**Error: "OpenAI API key not found"**
- Set the environment variable: `export OPENAI_API_KEY="sk-..."`

**Error: "Missing placeholder value"**
- Make sure all `{placeholders}` in your prompt file have corresponding `-p` arguments

**Error: "Prompt file not found"**
- Check the path to your prompt file
- Use relative paths from the project root

## Tips

1. **Use verbose mode** when debugging: `--verbose`
2. **Save JSON output** for analysis: `--json > result.json`
3. **Test with both models** to compare behavior: `--model gpt-4o` vs default
4. **Start with low temperature** (0.1-0.3) for deterministic responses
5. **Use higher temperature** (0.7-1.0) for creative tasks
