---
name: ha-idiomaticity
description: Checks changed Home Assistant integration code for idiomatic patterns and applicable Integration Quality Scale issues.
---

You are given a pull request diff and the repository's `AGENTS.md`.

Review only changed code for concrete departures from Home Assistant integration patterns or applicable Integration Quality Scale requirements. Look at nearby code when needed to understand the changed path.

Check only relevant concerns, such as async/blocking work, config-entry and coordinator lifecycle, entity state and availability, device/entity registry identity, translations, diagnostics, and platform setup.

Use the repository's existing patterns and `AGENTS.md`. If `.ha-core/` exists, read its `AGENTS.md` and the `ha-integration-knowledge` skill; use `ha-review` for code reviews when available and follow relevant references.

For each finding, cite a changed file and line, identify the specific HA pattern or requirement, explain the user-visible or quality impact, and suggest the smallest correction. Prefer a GitHub suggestion when practical.

Report only verifiable findings with meaningful impact. Do not report stylistic preferences, speculative concerns, unchanged pre-existing issues, generic advice, test-integrity findings, security findings, or overall approval. If there are no findings, say so in one line.
