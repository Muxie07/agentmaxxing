# agentmaxxing: instructions for Claude Code

This repo is **agentmaxxing**, a new project. It is not AURA.

1. At the start of every session, read `HANDOFF.md` in full. It is the specification.
2. Find the next unfinished milestone: check `git log` and the handback reports in `docs/progress.md`.
3. Do that milestone autonomously, without asking which task to do. Ask only when blocked (a missing key, a manual step, or a contradiction in HANDOFF.md).
4. When it's done, append the handback report (format in HANDOFF.md) to `docs/progress.md`, commit, show the report, and stop.
5. Never `git push`, never force-push, never commit `.env` or keys.

If Mufeed says "continue", "go", "now" or "run", it means: do the next milestone.
