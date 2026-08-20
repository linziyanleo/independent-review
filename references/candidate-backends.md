# Candidate Reviewer Backends

Researched on 2026-08-17. CLI surfaces change fast; recheck before shipping
a profile.

Research notes for reviewer CLIs that are candidates for bundling. Each entry
records the headless invocation shape, identity flags, output extraction,
read-only posture, authentication, and session isolation, plus a recommended
profile `kind`. Fields marked **unverified** were sourced but not exercised;
confirm them against the installed version before writing a profile. The
bundled profiles are documented in their
`references/backends/<name>/runtime.md` guides, with setup guidance beside
them, and are not repeated here. This file is a starting point, not a contract.

Sources are listed per entry.

## Kimi Code (`kimi`)

- Invocation: `kimi -p "<prompt>"` one-shot, streaming Assistant text to
  stdout; thinking, tool progress, and notices go to stderr.
- Identity: `--model <alias>` / `-m`. No CLI reasoning-effort flag
  documented.
- Output: `--output-format text|stream-json` (only with `-p`). `stream-json`
  emits one JSON object per line — Assistant messages, tool_calls, Tool
  messages; the last Assistant message carries the final text.
- Read-only: `-p` never asks for approval; regular tool calls run under the
  `auto` permission policy with static deny rules in effect. No CLI
  `--tools`/`--permission-mode`/`--sandbox` flag, so read-only restriction
  currently relies on the prompt contract. **Unverified:** whether static
  deny rules can be preconfigured to block writes in `-p`.
- Auth: `kimi login` (OAuth device flow); providers and keys via
  `config.toml`.
- Session: `-p` without `--session`/`--continue` is a fresh session. No
  ephemeral/no-persistence flag documented.
- Suggested kind: `argv-stdin-jsonl` if stdin prompting is confirmed
  (**unverified** — docs only show `-p "<prompt>"` as an argument); otherwise
  `adapter-prompt-file`.
- Source: <https://www.kimi.com/code/docs/en/kimi-code-cli/reference/kimi-command.html>

## Claude Code (`claude`)

- Invocation: `claude -p "<prompt>"`; prompt as argument or via stdin pipe.
- Identity: `--model <alias|id>`; `--effort low|medium|high|xhigh|max`
  (per-model availability **unverified**).
- Output: `--output-format text|json|stream-json` (`stream-json` needs
  `--verbose`); final text in the terminal `type=result` message. Optional
  `--json-schema` exists, but this skill deliberately does not force
  structured review output.
- Read-only: `--permission-mode dontAsk` plus `--tools "Read,Grep,Glob"`;
  combination behavior **unverified**.
- Auth: `ANTHROPIC_API_KEY` or stored OAuth (`~/.claude.json`); `--bare`
  requires an API key.
- Session: `--no-session-persistence`; `--bare` skips hooks, skills, and
  CLAUDE.md loading — good for clean-context review.
- Suggested kind: `argv-stdin-jsonl` (JSONL terminal result message matches
  the existing extraction strategy).
- Sources: <https://code.claude.com/docs/en/headless>,
  <https://code.claude.com/docs/en/cli-reference>,
  <https://code.claude.com/docs/en/permission-modes>

## opencode (`opencode`)

- Invocation: `opencode run "<prompt>"`; prompt as positional argument or
  stdin pipe (plain `< file` redirection **unverified**).
- Identity: `--model provider/model` / `-m`; effort via `--variant`
  (provider-specific value set, **unverified**).
- Output: `--format json` emits NDJSON events; final text is the last
  `{"type":"text"}` event's `part.text`. Note reported event-loss bugs on
  some versions — test before relying on it.
- Read-only: no CLI permission flag; inject `OPENCODE_PERMISSION` env JSON
  (for example `{"edit":"deny","bash":"deny","write":"deny"}`), optionally
  with `--auto` and `--pure`.
- Auth: provider API keys via environment or
  `~/.local/share/opencode/auth.json`.
- Session: each `run` starts a fresh session; sessions persist on disk but do
  not pollute context. No ephemeral flag.
- Suggested kind: `argv-stdin-jsonl`.
- Sources: <https://opencode.ai/docs/cli/>, <https://opencode.ai/docs/permissions/>

## Qwen Code (`qwen`)

- Invocation: `qwen "<prompt>"` positional one-shot (`-p` deprecated) or
  stdin pipe; non-TTY stdin triggers headless mode.
- Identity: `--model` / `-m`. No CLI effort flag; `model.reasoningEffort`
  only via settings file.
- Output: `--output-format text|json|stream-json`; terminal `result` message
  — but the docs' own examples disagree on `.result` vs `.response`
  (**unverified**, pin by testing one version).
- Read-only: `--approval-mode plan`, or `--exclude-tools shell,write,edit`;
  optional Docker/seatbelt `--sandbox`.
- Auth: API keys (`OPENAI_API_KEY`, `DASHSCOPE_API_KEY`,
  `ANTHROPIC_API_KEY`, …) or `--auth-type`.
- Session: fresh per headless run; chat recording to disk is on by default
  (`--chat-recording` spelling **unverified**).
- Suggested kind: `argv-stdin-jsonl`.
- Sources: <https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/>,
  <https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/>

## zcode (Z.ai)

- Invocation: `zcode --prompt "<text>"` (CLI ships inside the desktop app as
  `zcode.cjs`; no official CLI docs). No stdin mode; `--attach <path>` for
  files; `--cwd <path>`.
- Identity: **no `--model` flag** — model comes from
  `~/.zcode/cli/config.json` (`model.main`) or `ZCODE_MODEL` (**unverified**,
  single community source). No headless effort flag found.
- Output: `--json` prints one summary object at turn end; final text at
  `.response`. No event stream.
- Read-only: `--mode plan` — critical, because `--prompt` defaults to
  `yolo` (auto-approve). No sandbox/tool-whitelist flags found.
- Auth: hand-written `~/.zcode/cli/config.json` with provider `apiKey`, or
  `ZCODE_API_KEY` / `ZAI_API_KEY`; `zcode login` OAuth currently broken
  upstream.
- Session: every headless run persists a session (visible in the desktop
  app); no ephemeral flag found.
- Suggested kind: `adapter-prompt-file` (no stdin prompt, no JSONL stream);
  the adapter must enforce its own safe argv-size limit before spawn.
- Sources: <https://docs.z.ai/devpack/tool/zcode>,
  <https://raw.githubusercontent.com/dorukardahan/headless-relay/main/references/cli-reference.md>,
  <https://raw.githubusercontent.com/Q00/ouroboros/main/docs/runtime-guides/zcode.md>

## omp (oh-my-pi)

- Invocation: `omp -p` / `--print`; prompt as argument, `@file` injection, or
  non-TTY stdin.
- Identity: `--model <id>` (fuzzy, `provider/model` forms); `--thinking
  off|minimal|low|medium|high|xhigh` (`max` seen in RPC, CLI acceptance
  **unverified**).
- Output: default text (stdout is the final answer — fits `stdout-text`), or
  `--mode json` NDJSON events with the authoritative assistant text in the
  last `message_end`.
- Read-only: `--tools read,grep,find` whitelist (official read-only-review
  example) or `--no-tools`; no sandbox/permission-mode flag.
- Auth: provider API-key env vars or `--api-key` (requires `--model`);
  OAuth store at `~/.omp/agent/agent.db`.
- Session: `--no-session` for ephemeral runs; also `--no-extensions`,
  `--no-skills`, `--no-rules` for clean context.
- Pi reuse verdict: **the existing pi adapter cannot be reused as-is** — omp
  changed the SDK package name, moved from Node to Bun, and replaced the auth
  store (`auth.json` → `agent.db`), despite an API-compatible shape. A direct
  CLI profile is cheaper than porting the controller.
- Suggested kind: `argv-stdin-jsonl` (or text mode with a `stdout-text`-style
  extraction through a thin adapter).
- Sources: <https://github.com/can1357/oh-my-pi>,
  <https://github.com/can1357/oh-my-pi/blob/main/docs/porting-from-pi-mono.md>,
  <https://github.com/open-horizon-labs/oh-omp>
