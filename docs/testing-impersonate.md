
# GroupMe User Impersonation (Testing Only)

## Goal
Allow testing by posting GroupMe messages **on behalf of another user**, controlled by a feature flag. Default behavior remains unchanged.

---

## Default Behavior
- Feature flag **disabled** (default).
- Always use the **sender provided by GroupMe**.
- Ignore any impersonation markers in the message.

---

## Impersonation Trigger
- If feature flag is **enabled** and the message **starts with**:

```

{{@username}}

```

- Treat the message as coming from `username`.
- `username` will later be resolved via `roster.json`.
- Remove the prefix from the message before further processing.

Example:
```

{{@kohler}} start incident 12345

````

---

## When Feature Is Enabled
1. Check the beginning of the message text.
2. If `{{@username}}` is present:
   - Extract `username`
   - Replace the GroupMe sender with `username`
   - Strip the prefix from the message
3. If not present:
   - Use the original GroupMe sender

---

## Configuration
Add a flag to `poll.sh`:

```sh
ENABLE_USER_IMPERSONATION=false
````

* `false` (default): always use GroupMe sender
* `true`: allow impersonation via message prefix

---

## Implementation Requirements

* Impersonation logic must be isolated in its own method.

Example (conceptual):

```text
resolveCallingUser(message, impersonationEnabled)
```

This method:

* Applies the feature flag
* Parses `{{@username}}` if present
* Returns:

  * Resolved user
  * Cleaned message text

---

## Constraints

* Testing/dev use only
* No changes to GroupMe APIs
* No validation beyond later lookup in `roster.json`
* Downstream logic must only see the resolved user


