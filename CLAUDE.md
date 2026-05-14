@AGENTS.md

# Claude Code session conventions

Project-level rules are in `AGENTS.md` (imported above). This file is for Claude-Code-specific conventions only. Other agents (Cursor, Aider, Copilot) read `AGENTS.md` directly and never see this file.

## Memory directory

Claude Code session memory lives at `~/.claude/projects/<repo-hash>/memory/` and is loaded automatically into future Claude Code sessions. It is **Claude-Code-only** — other agents do not read it.

- Use memory for: cross-session reminders, lessons learned, project context that helps me work better in future Claude Code sessions.
- Do NOT use memory as the canonical home for any rule that all agents must follow. **If a rule starts in memory but applies across all agents working on this codebase, also add it to `AGENTS.md`.** Memory is a Claude-specific reinforcement, never the contract.

## Adding Claude-specific rules

Add new rules to this file ONLY when they are mechanically Claude-Code-specific (slash commands, internal tools, memory format). When in doubt, write to `AGENTS.md` instead so all agents benefit.
