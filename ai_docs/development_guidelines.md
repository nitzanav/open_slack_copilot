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
- **Validate-then-act for messy dicts** — parse raw `dict` into a small frozen dataclass (or `NamedTuple`); validation raises `ValueError` with a short message; one `try`/`except` at the boundary logs and returns; the happy path reads like plain logic on the typed object (e.g. `if now >= vm.expires_at`, `if vm.run_at`)
- **Encapsulate stored objects** — when the same record is read in many places, wrap it in a typed class with property getters that do the normalizing (`strip`, default, type-coerce). Callers write `conversation.last_final_text` / `conversation.current_or_first_step`, never `str(row.get("last_final_text") or "")` or `(row.get("current_step") or "").strip() or first_step(...)`. The dict shape stays an implementation detail of the storage module.
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
