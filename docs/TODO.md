- thumbs down (negative learning) — thumbs up is implemented and persists thumbed-up runs as skill examples
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
- ??? change M4 for watcher skills metabase.json to define who is the watcher user id. Not related to owner hcange it as wellpm
- track my follow ups, create task list for users with slack threads

CANCELLED
- seems not a real bug - suspected bug: when you have a recurring schedules, can it be that when shutting the process down for a few days, after starting it off it will run multiple tasks?
