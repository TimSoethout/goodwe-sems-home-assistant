# Contributing to GoodWe SEMS Home Assistant Integration

Thanks for contributing to the GoodWe SEMS Home Assistant integration.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Making Changes](#making-changes)
- [Code Quality](#code-quality)
- [Testing](#testing)
- [Submitting Changes](#submitting-changes)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Code Review Process](#code-review-process)

## Code of Conduct

Follow the project's [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### Prerequisites

- Python 3.14, Git, and a GitHub account
- [uv](https://docs.astral.sh/uv/) for standalone setup
- Home Assistant custom component or GoodWe SEMS familiarity is helpful, not required

### Finding Issues to Work On

Find work in [Issues](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues)
(`good first issue` or `help wanted`) or [Discussions](https://github.com/TimSoethout/goodwe-sems-home-assistant/discussions).
Discuss unlisted feature ideas in an issue before starting.

## Development Setup

For the recommended Home Assistant Core Dev Container, follow the
[README development setup](README.md#development-setup). For standalone tests
and linting, fork and clone the repository, then install:

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -r requirements.test.txt ruff mypy
```

## Making Changes

### Branch Naming

Use a descriptive branch name, such as `feature/add-xyz`, `fix/issue-123`,
`docs/update-readme`, or `refactor/improve-xyz`.

### Code Style

Follow [PEP 8](https://peps.python.org/pep-0008/), Home Assistant's
[developer documentation](https://developers.home-assistant.io/), and existing
patterns. Ruff handles formatting and imports; `pyproject.toml` sets the
88-character line length.

Integration code lives in `custom_components/sems/`; see the
[architecture plan](ARCHITECTURE_PLAN.md) for its data flow.

## Code Quality

### Linting

This project uses **Ruff** for linting and formatting, and **mypy** for type checking.

**Run all linting checks (same as CI):**
```bash
ruff check custom_components/
ruff format --check custom_components/
mypy custom_components/ --ignore-missing-imports --python-version 3.14
```

**Fix linting issues automatically:**
```bash
ruff check --fix custom_components/
ruff format custom_components/
```

Add type hints to new or changed functions and verify them with the `mypy`
command above.

### Documentation

Update the README or other relevant user-facing docs and `strings.json` when UI
text changes. Add code comments only to explain non-obvious behavior.

## Testing

Use [tests/README.md](tests/README.md) for full and targeted test commands,
coverage, and Home Assistant Core instructions. CI requires 80% overall
coverage; focus tests on changed behavior rather than a per-change percentage.
Include component tests where useful; follow existing patterns, keep tests
isolated, use `requests-mock` for HTTP, and never call the live GoodWe API.

## Submitting Changes

Fork the repository, branch from `master`, make a focused change, run the checks
above, then push and open a PR using the
[pull request template](.github/pull_request_template.md). Link an issue when
relevant; use `Closes #123` only when the PR closes it.

## Commit Message Guidelines

Use [Conventional Commits](https://www.conventionalcommits.org/), in the form
`<type>(<scope>): <subject>`.

### Types

- `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

These are common types, not an exhaustive list; use another descriptive type
when it better fits the change.

There is no documented SemVer bump policy. Maintainers update
[`manifest.json`](custom_components/sems/manifest.json) manually; commit types
don't automate version bumps, and publishing a GitHub release triggers
packaging.

### Examples

- `feat(api): support multiple power stations` (`Refs #45`)
- `fix(sensor): handle null values` (`Fixes #123`)
- `docs: update development setup`

## Code Review Process

Maintainers review PRs as available and may request changes; those with no
activity for 90 days may be closed and reopened when work resumes. Reviews
prioritize requested behavior, then code quality, tests, user-facing docs,
compatibility, security, and performance. Add code comments only for
non-obvious behavior.

## Questions?

Use the Issues or Discussions links above for questions.

## License

Contributions are licensed under the project's [LICENSE](LICENSE).

---

Thanks for helping improve the integration.
