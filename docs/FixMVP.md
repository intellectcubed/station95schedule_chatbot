
# AI Code Modification Specification — Schedule Interpretation & Context Enrichment

## Actors
- **schedule-chatbot**  
  Polls GroupMe, updates the database, invokes calendar-service actions.
- **chat-database (Supabase)**  
  Stores workflow state and conversation history.
- **calendar-service**  
  Manages the physical Google Calendar representing the collaborative schedule.
- **Humans**  
  Members of the GroupMe chat representing rescue squads.
- **LLM (ChatGPT)**  
  Interprets human messages and translates intent into tool invocations.

---

## Problem Statement

### Example Human Message
```

For Sunday we have a crew from 0700-1200.
And Midnight-0600

We are still in need of coverage from
0600-0700. 1200-1800 and 1800-0000

````

### Observed Issues
1. **Incorrect Action Type**
   - The LLM inferred `addShift` actions for uncovered time ranges.
   - Correct action should be `noCrew` for those ranges.
   - Semantics:
     - `addShift`: squad is committing to staff a shift.
     - `noCrew`: squad was expected to staff but does not have coverage.
   - The message clearly indicates lack of coverage.

2. **Missing Squad Context**
   - The LLM did not know which squad the message applied to.
   - In this case, the message sender (`Geo Now`) maps to squad **43** via `roster.json`.
   - Squad context should be implied from the sender unless overridden.

3. **Lack of Calendar State**
   - The LLM did not know:
     - Which squads are currently scheduled
     - Which shifts already have coverage
   - This prevented correct interpretation of intent.

---

## Root Cause

The LLM is invoked with:
- The human message
- A generic system prompt (`ai_prompts/system_prompt.txt`)

But it lacks:
1. The squad represented by the message sender
2. The current schedule state for the relevant day(s)

---

## Proposed Solution: Two-Phase LLM Interaction with Preprocessing

### 1. Sender-to-Squad Resolution (Preprocessing)
- **schedule-chatbot** must determine which squad the message sender represents.
- Lookup performed against `roster.json`.
- This step is **deterministic** and does **not** involve the LLM.

---

### 2. Abbreviated LLM Prompt (Intent + Day Resolution)

Before invoking the full system prompt, call the LLM with a **minimal prompt** to determine:

- Is the message related to **shift coverage** (vs. noise)?
- What **day or days** does the message refer to?

#### Output Expected from LLM
- `isShiftCoverageMessage: boolean`
- `resolvedDay(s): [YYYY-MM-DD]`

#### Day Resolution Rules (Clarified)
- Schedules are typically discussed in terms of a **single 24-hour operational day**.
- Time references must be interpreted relative to that day:

Examples:
- “Tomorrow 0600–1800”  
  → Tomorrow morning 06:00 to 18:00.
- “Tomorrow midnight to 0600”  
  → If tomorrow is Tuesday, this refers to **Tuesday night shift**, i.e.  
    **Tuesday 18:00 → Wednesday 06:00**, specifically the **00:00–06:00** portion.
- Midnight references **belong to the night shift of the named day**, not the following day.

This nuance must be explicitly handled in the abbreviated prompt logic.

---

### 3. Calendar State Retrieval
- Using the resolved day(s), **schedule-chatbot** calls **calendar-service** to retrieve the current schedule.

---

### 4. Full LLM Invocation (Decision & Actions)
- Call the LLM with:
  - Full `system_prompt.txt`
  - Human message
  - Resolved squad ID
  - Current schedule state for the relevant day(s)
  - Conversation context (last 10–20 messages with this user)

- The LLM then:
  - Correctly distinguishes `addShift` vs `noCrew`
  - Applies actions to the correct squad
  - Produces tool invocations for `calendar-service`

---

## Current Schedule Format (Context Provided to LLM)

The schedule is represented as a JSON object with the following structure:

```json
{
  "day": "Saturday 2025-12-27",
  "shifts": [
    {
      "name": "06:00 - 07:00 Shift",
      "start_time": "06:00",
      "end_time": "07:00",
      "segments": [
        {
          "start_time": "06:00",
          "end_time": "07:00",
          "squads": [
            { "id": 42, "territories": [], "active": false },
            { "id": 43, "territories": [34, 35, 42, 43, 54], "active": true },
            { "id": 54, "territories": [], "active": false }
          ]
        }
      ],
      "tango": 43
    },
    {
      "name": "07:00 - 12:00 Shift",
      "start_time": "07:00",
      "end_time": "12:00",
      "segments": [
        {
          "start_time": "07:00",
          "end_time": "12:00",
          "squads": [
            { "id": 42, "territories": [34, 35, 42, 43, 54], "active": true },
            { "id": 54, "territories": [], "active": false }
          ]
        }
      ],
      "tango": 42
    },
    {
      "name": "12:00 - 18:00 Shift",
      "start_time": "12:00",
      "end_time": "18:00",
      "segments": [
        {
          "start_time": "12:00",
          "end_time": "18:00",
          "squads": [
            { "id": 42, "territories": [], "active": false },
            { "id": 54, "territories": [34, 35, 42, 43, 54], "active": true }
          ]
        }
      ],
      "tango": 54
    },
    {
      "name": "Night Shift",
      "start_time": "18:00",
      "end_time": "06:00",
      "segments": [
        {
          "start_time": "18:00",
          "end_time": "06:00",
          "squads": [
            { "id": 42, "territories": [34, 35, 42, 43, 54], "active": true }
          ]
        }
      ],
      "tango": 42
    }
  ]
}
````

---

## Clarification Handling

* The **schedule-chatbot** may ask follow-up questions if intent or timing is ambiguous.
* While awaiting clarification, the workflow is paused.
* Upon user response, the workflow resumes from the abbreviated prompt phase.

---

## Summary

* Resolve squad deterministically before LLM usage
* Use a lightweight LLM call to determine intent and day(s)
* Provide full schedule context before action inference
* Explicitly encode day-boundary semantics for night shifts
* Enable correct differentiation between `addShift` and `noCrew`


