# User Impersonation Feature - Testing Guide

## Overview
The user impersonation feature allows testing the chatbot by sending messages **as if they came from another user** in the roster. This is useful for testing workflows without needing multiple GroupMe accounts.

⚠️ **FOR TESTING ONLY** - This feature should only be enabled in development/test environments.

---

## Configuration

### Enable the Feature
Add to your `.env` file:
```bash
ENABLE_USER_IMPERSONATION=true
```

Default is `false` (disabled).

### When Enabled
The bot will log a warning on startup:
```
⚠️  User impersonation is ENABLED - for testing only!
```

---

## Usage

### Syntax
Send a message starting with:
```
{{@username}} your message here
```

- `username` must match a `name` or `groupme_name` in your `roster.json`
- The prefix will be stripped before processing
- The message will be treated as coming from that user

### Examples

**Example 1: Impersonate user "kohler"**
```
{{@kohler}} Squad 42 can't make tonight
```
- Bot treats this as if kohler sent: "Squad 42 can't make tonight"
- Resolves kohler's squad and role from roster
- Logs: `🎭 Impersonating user: kohler (squad 42, Chief)`

**Example 2: Multiple words after prefix**
```
{{@smith}} Looking for an EMT tonight, I only have 1 right now
```
- Bot treats this as if smith sent the message
- Uses smith's squad/role for workflow context

**Example 3: Non-existent user**
```
{{@nobody}} test message
```
- Bot logs: `⚠️  Impersonation failed: user 'nobody' not found in roster`
- Falls back to actual GroupMe sender
- Still strips the prefix from message

---

## How It Works

### Implementation Details

1. **Feature Flag Check**
   - If `ENABLE_USER_IMPERSONATION=false`, impersonation is completely disabled
   - Original sender and message are used as-is

2. **Pattern Matching**
   - Regex: `^\{\{@(\w+)\}\}\s*`
   - Matches `{{@username}}` at start of message
   - Captures the username

3. **Roster Lookup**
   - Searches `roster.json` for matching user
   - Uses `find_member_by_name()` (case-insensitive)
   - Returns user's `groupme_name`, `squad`, and `title`

4. **Message Processing**
   - Resolved username replaces GroupMe sender
   - Prefix is stripped from message text
   - Downstream code sees only the resolved user

### Code Flow
```
GroupMe Message → _resolve_calling_user() → Cleaned Message → Workflow Processing
                         ↓
                  Roster Lookup
```

---

## Logging

### When Impersonation Succeeds
```
INFO: 🎭 Impersonating user: kohler (squad 42, Chief)
```

### When User Not Found
```
WARNING: ⚠️  Impersonation failed: user 'nobody' not found in roster. Using original sender.
```

### Startup Warning
```
WARNING: ⚠️  User impersonation is ENABLED - for testing only!
```

---

## Testing Examples

### Test 1: Basic Impersonation
**Setup:** ENABLE_USER_IMPERSONATION=true
**Message:** `{{@kohler}} Squad 42 can't make Saturday night`
**Expected:**
- Sender: kohler
- Message: "Squad 42 can't make Saturday night"
- Squad: 42
- Role: Chief

### Test 2: Disabled Feature
**Setup:** ENABLE_USER_IMPERSONATION=false
**Message:** `{{@kohler}} test message`
**Expected:**
- Sender: <actual GroupMe sender>
- Message: "{{@kohler}} test message" (prefix NOT stripped)

### Test 3: Invalid User
**Setup:** ENABLE_USER_IMPERSONATION=true
**Message:** `{{@invalid}} test message`
**Expected:**
- Warning logged
- Sender: <actual GroupMe sender>
- Message: "test message" (prefix IS stripped)

---

## Security Considerations

1. **Testing Only:** Never enable in production
2. **No Authentication:** Anyone who can message the bot can impersonate
3. **Roster Required:** Only users in roster.json can be impersonated
4. **Audit Trail:** All impersonations are logged with 🎭 emoji

---

## Disabling the Feature

1. Remove or set to false in `.env`:
   ```bash
   ENABLE_USER_IMPERSONATION=false
   ```

2. Restart the bot

3. All messages will use actual GroupMe sender
