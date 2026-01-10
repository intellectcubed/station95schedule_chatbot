Group Me poller requirements


## Overall processing
- request received from user
  - is there an open workflow for this user?
  - No: Process as message
  - Yes: Is the workflow older than 2 hours?
    - Yes: Cancel workflow, process as new message
    - No: Continue Workflow

- Continue workflow.
  - Get context messages from DB
  - post message to LLM asking if this is in response to the thread (if there is a pending question)
  - Return the request in the form of a new request with the clarification
  - Close workflow
  - Process new request

- Process as a message
  - Call upon intent handler to see if there is an intent in the message
  - If shift request - make a call to calendar service to get the schedule for the day mentioned
  - Call LLM with context, current message, 


## High level requirements/hints
  - Write to chatbot.log, errors to error.log, llm messages (to and from) to llm.log
  - Use rotating log file handler
  - When posting to LLM, keep the LLM prompt outside of the class in its own resource file.  Read this file in to format the LLM prompt
  



Scenario:
Human: 35 does not have a crew tonight from 1800 - 2000
LLM: "⚠️ WARNING ⚠️
  Squad 35 is not currently scheduled for tonight (2025-12-30) from 1800 to 2000, so they cannot request removal. Perhaps there's a misunderstanding about the
  schedule, or they meant to discuss a different date?".  
  ## workflow status was set to 'NEW'

Human: "sorry, i meant tomorrow night"
chatbot: no action taken


  I think the correct way for this to be handled should be:
  - chatbot recognizes that there is a previously opened workflow (especially with this user)
  - Get the conversation context for the workflow and send to LLM to determine if this is a response to that workflow, or if it is a new request, or noise.
  - After determining that it is a response to question, send the context and new question to LLM 
  - LLM should return along the lines of: "35 is notifying that tomorrow night they have no crew from 1800 to 2000"
  - The Chatbot should then: 
    - Keep the workflow open
    - Process the newly interpreted message '35 has no crew tomorrow night from 1800 to 2000'
    - (normal processing of the interpreted message)
    - If no further questions and the interpreted message is handled, chatbot should set workflow to completed.








Asking LLM if new question:

## Scenario: We are processing messages from a group chat.  A new message has been received from a user, and that user has an open workflow.  
## Task: We need to determine if this is a continuation of the workflow, or is this a new, unrelated question?  Answer in the form of a new question posed by the user.

## Example scenario:
User: 35 has no crew for tonight 1800 - 2000
Chatbot: ⚠️ WARNING ⚠️
  Squad 35 is not currently scheduled for tonight (2025-12-30) from 1800 to 2000, so they cannot request removal. Perhaps there's a misunderstanding about the
  schedule, or they meant to discuss a different date?"
User: sorry, I meant to say tomorrow night, not tonight

Analysis: We have determined that the user is answering the question on which the workflow is paused.  It should respond with a new question: 

Response: 
{
   "isResponse": True,
   "modifiedIntent": ""
}

Answer from LLM: The user is stating that 35 has no crew for tomorrow night from 1800 - 2000

## Canonical roles

**system** – rules, instructions, workflow state

**user** – human messages

**assistant** – LLM responses

**tool** (optional) – tool calls / system outputs

Here is the current context: 

```
[
  {
    "role": "system",
    "content": "You are a scheduling assistant for rescue squad coverage."
  },
  {
    "role": "user",
    "content": "35 does not have a crew tonight from 1800 - 2000"
  },
  {
    "role": "assistant",
    "content": "⚠️ Squad 35 is not currently scheduled for tonight..."
  },
  {
    "role": "user",
    "content": "sorry, i meant tomorrow night"
  }
]
```