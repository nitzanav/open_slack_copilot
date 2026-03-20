---
name: test-commit-push
description: Test, commit and push to git remote.
---

# Commit and Push by Task

Apply when the user asks to commit, push

## Workflow

1. `git status` → see what changed
3. `git add <paths>`
4. `git commit -m "type(scope): description"`
4. `git push`

**Rules:** Prefer 1 commit when cohesive. Use conventional commits (feat, fix, refactor). If unsure, don't split.
