# Development Guidelines (Summary)

> Full document: [docs/development_guidelines.md](../docs/development_guidelines.md)

## Coding Standards

- **KISS** — minimum layers, no unnecessary abstraction
- **Decoupled & testable** — each file/folder = standalone package, single responsibility
- **Small functions, top-down** — hide checks/boilerplate in sub-functions; function names replace comments
- **No noise** — no logs (use `@log` decorator), comments only for "why"; no inline boilerplate
- **Short code** — take assumptions, skip unnecessary validations
- **Meaningful names** — name by *what* it does for the caller, not *how*; delete dead code
- **Validation pattern** — raise private `_ValidationError`, catch once at top of handler
- **Extract 6+ line blocks** into named functions explaining the *what*
- **Prefer external packages** — only if keeps code simpler
- **Docs** — concise `.md`, 2-7 bold-titled bullets, 2-10 words each

## Task Flow

Vision → spec `.md` → STP with edge cases → code per standards → unit tests (mock LLM/Slack) → integration tests

## Tests

- Mock only Slack API & LLM; simulate full Slack input per use case
- Assert both the prompt sent to AI and the draft output
- Edge cases: regular thread, new messages after draft, singleton thread, huge threads, PMs

## Folder Convention

- `.md` design doc per folder and per capability
- `_unit_test.py` per file, `_integration_test.py` for integration
- One capability per file, one group per folder
