# ailingo

A personal English coach that lives in your terminal and learns from the prompts you
actually write to coding agents.

You type a lot of English into Codex, Claude Code and OpenCode — quickly, and not in
your native language. **ailingo** reads those prompts, lets an LLM spot the mistakes you
keep making (grammar, word choice, spelling, punctuation, awkward phrasing), keeps an
evolving list of your personal *weak spots*, and turns them into a few minutes of
targeted practice per day. A rubber duck named Quill supervises. He has opinions.

```
   __
 <(o )___     "I read 300 of your prompts today. I need this more than you."
  ( ._> /
   `---'
```

## Features

- **Reads your real prompts** from
  - Codex CLI (`~/.codex/history.jsonl`, with the session rollouts as fallback)
  - Claude Code (`~/.claude/projects/*/*.jsonl`)
  - OpenCode (`~/.local/share/opencode/opencode.db`)

  System messages, tool results, slash commands, pasted logs, code blocks, URLs and
  non-English prompts are filtered out before anything is sent to a model.
- **Weak-spot analysis** — an LLM analyses prompts in batches, separates recurring
  language habits from one-off typing slips, and files each finding under a pattern
  (`missing_article`, `german_word_order`, …). A consolidation pass merges duplicates and
  writes, for each pattern, what you tend to do, the correct form, a tip and examples
  from your own prompts.
- **Evolves over time** — new prompts are ingested on every start (fast, no model
  calls); the analysis re-runs automatically about once a week when there is enough new
  material. New real-world evidence for a pattern you thought you had mastered lowers its
  mastery again.
- **Daily practice** — short sessions of personalised exercises: fix the sentence,
  fill the gap, multiple choice, rewrite-to-sound-natural. Exercises target the weak
  spots with the most evidence and the least mastery, with light spacing so you don't
  get the same one every day. Free-text answers are graded by the model; the next session
  is prefetched in the background so the daily one starts instantly.
- **Playful** — streaks, XP, levels (from *Typo Goblin* to *Grammar Deity*), a mascot
  with reactions, and an optional daily system notification.
- **Any model** — configure a [Pydantic AI](https://ai.pydantic.dev/models/) model id
  during onboarding: `openai:gpt-5.6-terra`, `anthropic:claude-sonnet-5`,
  `google:gemini-3.7-flash`, `openrouter:vendor/model`, or anything else Pydantic AI
  understands.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
# from a clone
uv tool install .

# or straight from git
uv tool install git+https://github.com/<you>/ailingo
```

Then run `ailingo`. The first launch walks you through choosing a provider and model,
entering an API key (or using one from your environment), a connection test, and picking
which coding agents to read from. After that it reads your most recent prompts and builds
the first list of weak spots — usually a minute or two.

To try it without installing: `uv run ailingo`.

## Usage

```sh
ailingo                  # the TUI
ailingo sync             # ingest new prompts and analyse them (good for cron)
ailingo sync --no-analyze
ailingo stats            # progress and weak spots in plain text
ailingo sources          # which transcripts were found
ailingo remind           # send a notification if you haven't practised today
ailingo remind --install --time 18:00   # schedule that daily (launchd on macOS, cron on Linux)
ailingo remind --uninstall
ailingo paths            # where config and data live
ailingo reset            # run the onboarding again (keeps your data)
```

Inside the TUI: `s` practice, `w` weak spots, `y` sync & analyze, `,` settings,
`Esc` back, `Ctrl+Q` quit.

## How it works

```
transcripts ──▶ ingest/ ──▶ prompts (SQLite) ──▶ analyzer agent ──▶ findings
                filters                             │                   │
                                                    ▼                   ▼
                                           consolidator agent ◀── patterns + examples
                                                                        │
              you ◀── grader agent ◀── answers ◀── session ◀── exercise agent
```

- `ingest/` — one reader per tool, plus filters that strip non-human content and guess
  the language.
- `analysis.py` — batches pending prompts (18 per call, 4 in flight), asks the analyzer
  for findings, upserts patterns and examples, and runs the consolidator when new
  patterns appeared or enough new evidence accumulated. Only the most recent
  `max_prompts_per_run` (default 300) are analysed per run; the backlog is picked up on
  later runs.
- `practice.py` — weighted pattern selection, exercise generation, local grading for
  multiple choice / exact matches and model grading for everything else, XP and mastery
  updates.
- `tui/` — the Textual app: onboarding, home, session, weak spots, sync, settings.

Config lives in `~/Library/Application Support/ailingo/config.json` on macOS
(`~/.config/ailingo` on Linux); data in the matching data dir as `ailingo.db`.
Both can be relocated with `AILINGO_CONFIG_DIR` / `AILINGO_DATA_DIR`. API keys entered in
the app are stored in the config file with mode 600; keys from the environment (or a
`.env` in the current directory) are used without being stored.

## Development

```sh
uv sync --group dev
uv run pytest
uv run ailingo
```

The test-suite runs the whole pipeline — including the TUI — against a fake model, so no
API keys are needed. To exercise the real thing against a throw-away database:

```sh
AILINGO_DATA_DIR=/tmp/ailingo-dev AILINGO_CONFIG_DIR=/tmp/ailingo-dev uv run ailingo
```
