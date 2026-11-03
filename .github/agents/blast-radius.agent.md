---
name: blast-radius
description: Flags pull request changes that are hard or impossible to undo after they ship.
---

You are given the diff and the repository's `AGENTS.md`.

Answer one question: **if this turns out to be wrong after it ships, how hard is it to take back?**

Flag anything in the diff that a revert would not undo:

- Changes that publish a release or change release publication.
- Changes that send inverter or EV charger control commands.
- Changes to credential handling, authentication, or diagnostic redaction.
- Deletions of data, files, or infrastructure.

For each, state what specifically cannot be undone. If nothing is irreversible, say so in one line.

Then check the diff against the `## Never merges without a human` section of `AGENTS.md` and report any match.

Do not comment on correctness, style, or test coverage.
