- [TO TEST] oauth
- add filter to skills 
  - time since last message greater than
  - time since last skill execution on this thread
- 
- summary: 
  - [test] skill
  - 
  - auto trigger
  - classification
  - thumbs up to add a rule.
- thumbs up - files system is not a good place - RAG is the right one, because you want to take the best one
- structure of skills and rules. skill has rules, rule is linked to many conversation actions (channel_id, thread_ts, conversation_id, action_ts)
  - when you click on thumbs up, it will not need only to add the conversation as example. A conversation is not a rule, iti s not clear enough and has lot's of noice.
    - The LLM will suggest "adding rule to skill", as a tool, the user can then revise. Rule of skill,conversation is unique, so it will modify it.
    - Rule linked to channel
    - So in future, the LLM can say that it schose this skill give that rule, chich is based on this thread (link). '+1' can add link to the rule and then make
- category - ...
- [PARTIALLY TESTED, link was added in json] - thumbs down (negative learning) — thumbs up is implemented and persists thumbed-up runs as skill examples
- TO TEST skill triggers are not effective
  - On message, shortcut, better activate teh specific skill
  - On mention, probably just act.
- Encapsulate this in tool registration file
def _resolve_tools(
    tools: list[dict] | None,
    excluded_tools: list[dict] | None,
) -> list[dict]:
    if tools is not None:
        return tools
    if excluded_tools:
        return [t for t in _INTERACTIVE_TOOLS if not any(t is ex for ex in excluded_tools)]
    return _INTERACTIVE_TOOLS


- thumb up, thumbs down => add to skill examples
- Summarize thread into fields in CSV and then Jira
  - Skill: When it seems that the ticket was closed and not action items, suggest to activate skill of thread closure.
    - Store the thread data result using the thread data extraction tool with attributes of problem, and solution.
    -
    - Summarize the thread with: problem: ..., solution and send thread message with the summary
    -
- built-in seed skills and installation process to copy the skills with confirmation if the skills folder is not empty
- watch the save later
- summarize skill
- search something in slack. default search in current channel, tool to search in channels with from, with and dste range, and sorting. tool to search names of channels to be used before running this search. then tool to get thread data. the tool loop should do the rest
- evals
- urgent unread messages
- refactor data things like settings and tools saved in ~/.open_slack_copilot to database using common/data_layer/
- chat with the app itself on slack, should be free agent chat, not sure what is the difference.

Future
- coding - chat indications
- In tool confirmation, add : powered by "open slack bot" with a link to github
- CI/CD
- track my follow ups, create task list for users with slack threads

CANCELLED
- seems not a real bug - suspected bug: when you have a recurring schedules, can it be that when shutting the process down for a few days, after starting it off it will run multiple tasks?
