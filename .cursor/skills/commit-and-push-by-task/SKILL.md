---
name: commit-and-push-by-task
description: Commits and pushes changes from the chat session, grouping edits into logical tasks. One commit per task. Use when the user asks to commit, push, save work, or persist changes from the conversation.
---

# Commit and Push by Task

Apply when the user asks to commit, push, or save changes from this chat.

**Task** = substantial unit of work (feature, bugfix, refactor), not tiny edits. Usually 1 per chat, max 2–3.

## Workflow

1. `git status` → see what changed
2. Group into 1–3 tasks based on purpose (same effort → one task; unrelated → separate)
3. For each task: `git add <paths>` then `git commit -m "type(scope): description"`
4. `git push`

**Single task (common):** `git add -A && git commit -m "feat(scope): msg" && git push`

**Rules:** Prefer 1 commit when cohesive. Use conventional commits (feat, fix, refactor). If unsure, don't split.
