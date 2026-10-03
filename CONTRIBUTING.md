# Contributing to GoodWe SEMS Home Assistant Integration

Thank you for your interest in contributing to the GoodWe SEMS Home Assistant Integration! We appreciate contributions from the community.

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

This project adheres to a code of conduct that all contributors are expected to follow. Please be respectful, inclusive, and considerate in all interactions with the community.

## Getting Started

### Prerequisites

- Python 3.14
- Git
- A GitHub account
- Basic understanding of Home Assistant custom components
- Familiarity with the GoodWe SEMS API (helpful but not required)

### Finding Issues to Work On

- Check the [Issues](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues) page
- Look for issues labeled `good first issue` or `help wanted`
- Check [Discussions](https://github.com/TimSoethout/goodwe-sems-home-assistant/discussions) for feature requests
- If you want to work on something not listed, create an issue first to discuss it

## Development Setup

There are two ways to set up your development environment:

### Option 1: Home Assistant Core Dev Container (Recommended)

Follow the [Development setup](README.md#development-setup) in the README. The Dev Container installs dependencies, checks out Home Assistant Core, and links the integration.

### Option 2: Standalone Testing Environment

For running tests and linting without a full Home Assistant setup:

1. **Fork and clone the repository:**
   ```bash
   git clone https://github.com/YOUR_USERNAME/goodwe-sems-home-assistant.git
   cd goodwe-sems-home-assistant
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.test.txt
   pip install ruff mypy
   ```

## Making Changes

### Branch Naming

Use a descriptive branch name. These are examples, not a required list:
- `feature/add-xyz` - for new features
- `fix/issue-123` - for bug fixes
- `docs/update-readme` - for documentation changes
- `refactor/improve-xyz` - for code refactoring

### Code Style

This project follows Home Assistant's coding standards:

- **Python Style Guide:** [PEP 8](https://www.python.org/dev/peps/pep-0008/)
- **Line Length:** 88 characters (configured in `pyproject.toml`)
- **Quotes:** Double quotes for strings
- **Import Sorting:** Automated with Ruff (isort)

### Key Files and Their Purpose

- `custom_components/sems/`:
  - `__init__.py` - Integration setup and configuration
  - `config_flow.py` - Configuration UI flow
  - `sems_api.py` - Core API client for GoodWe SEMS
  - `sensor.py` - Sensor entity implementations
  - `switch.py` - Switch entity for inverter control
  - `const.py` - Constants and configuration
  - `device.py` - Device information
  - `manifest.json` - Integration metadata
  - `strings.json` - UI text strings
  - `translations/` - Localized strings

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

### Type Hints

- Add type hints to all function signatures
- Use `from typing import` for complex types
- Run `mypy` to verify type correctness

### Documentation

- Document public APIs when needed to explain their behavior
- Use clear, descriptive variable and function names
- Update README.md if your changes affect user-facing features
- Update `strings.json` for any UI text changes

## Testing

### Running Tests

Run all tests:
```bash
python -m pytest tests/ -v
```

See [tests/README.md](tests/README.md) for targeted test, coverage, and Home Assistant Core workspace instructions.

### Writing Tests

- Add or update automated tests for behavior changes where appropriate, including integration/component tests when useful
- Follow the existing test patterns in `tests/`
- Use `requests-mock` for mocking HTTP calls
- Ensure tests are isolated and don't depend on external services
- There is no fixed coverage target; focus on exercising the changed behavior

## Submitting Changes

### Pull Request Process

1. **Update your fork:**
   ```bash
   git checkout master
   git pull upstream master
   ```

2. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes:**
   - Write code following the style guidelines
   - Add or update tests
   - Update documentation if needed

4. **Verify your changes:** Run the applicable checks in Code Quality and Testing above.

5. **Commit your changes:**
   ```bash
   git add path/to/changed-files
   git commit -m "Add feature: your feature description"
   ```

6. **Push to your fork:**
   ```bash
   git push origin feature/your-feature-name
   ```

7. **Create a Pull Request:**
   - Go to the [repository](https://github.com/TimSoethout/goodwe-sems-home-assistant)
   - Click "New Pull Request"
   - Select your branch
   - Fill out the PR template with a clear description
   - Link any related issues

### Pull Request Guidelines

Your PR should:

- Have a clear, descriptive title
- Include a detailed description of what changed and why
- Link related issues when applicable; use `Closes #123` only when the PR closes the issue
- Include tests for behavior changes where appropriate
- Pass all CI checks (tests, linting, validation)
- Have a single, focused purpose (avoid mixing unrelated changes)
- Update documentation if user-facing changes are made

## Commit Message Guidelines

Follow the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types

- `feat:` - A new feature
- `fix:` - A bug fix
- `docs:` - Documentation only changes
- `style:` - Code style changes (formatting, no logic change)
- `refactor:` - Code refactoring (no functional changes)
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks, dependency updates

The repository does not currently document a SemVer bump policy. Maintainers update the version in `custom_components/sems/manifest.json`; Conventional Commit types do not automate version bumps, and publishing a GitHub release triggers the packaging workflow.

### Examples

```
feat(api): add support for multiple power stations

Add ability to configure and monitor multiple power stations
from a single integration instance.

Refs #45
```

```
fix(sensor): handle null values in inverter data

Previously, null values would cause sensor updates to fail.
Now they are handled gracefully with default values.

Fixes #123
```

```
docs: update development setup instructions

Clarify the steps for setting up the development environment
with Home Assistant core.
```

## Code Review Process

### What to Expect

- A maintainer will review your PR, usually within a few days
- You may be asked to make changes or clarifications
- Be responsive to feedback and questions
- Once approved, a maintainer will merge your PR

### Review Criteria

Reviewers will check for:

- Code quality and adherence to style guidelines
- The change meets the behavior requested in the issue or pull request
- Tests exercise changed behavior where appropriate, and CI checks pass
- User-facing documentation is updated when needed; code comments are only needed to explain non-obvious behavior
- No breaking changes (or properly documented/versioned if necessary)
- Security considerations
- Performance implications

## Additional Resources

- [Home Assistant Developer Documentation](https://developers.home-assistant.io/)
- [Home Assistant Architecture](https://developers.home-assistant.io/docs/architecture_index)
- [Creating Custom Components](https://developers.home-assistant.io/docs/creating_component_index)
- [GoodWe SEMS Portal](https://www.semsportal.com)

## Questions?

- Check existing [Issues](https://github.com/TimSoethout/goodwe-sems-home-assistant/issues)
- Start a [Discussion](https://github.com/TimSoethout/goodwe-sems-home-assistant/discussions)
- Reach out to the maintainers

## License

By contributing to this project, you agree that your contributions will be licensed under the same license as the project (see LICENSE file).

---

Thank you for contributing! Your efforts help make this integration better for everyone. 🎉
