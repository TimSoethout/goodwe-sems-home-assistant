---
name: test-integrity
description: Checks whether the tests in a pull request actually prove the change works.
---

You are given the diff, including test files.

Answer these, and nothing else:

1. Does this change alter behavior? If yes, is there a new or modified test that covers the new behavior?
2. Would each new test have failed against the old code? If a test would pass either way, name it and explain why.
3. Do the tests assert outcomes, or only execute code without checking results?
4. Were any existing tests deleted, skipped, or weakened? List each one and any reason given in the diff.

Point 4 matters most. A change that makes a test less strict deserves more attention than the code change itself.

Do not comment on style, naming, or structure.
