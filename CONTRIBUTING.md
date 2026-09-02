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

- Python 3.13 or higher
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

### Option 1: Home Assistant Core Development Environment (Recommended)

This is the recommended approach for developing Home Assistant custom components:

1. **Set up Home Assistant Core development environment:**
   ```bash
   # Follow the official guide:
   # https://developers.home-assistant.io/docs/development_environment
   ```

2. **Clone this repository in the config directory:**
   ```bash
   cd core/config
   git clone https://github.com/TimSoethout/goodwe-sems-home-assistant.git
   ```

3. **Create a symbolic link:**
   ```bash
   cd core/config/custom_components
   ln -s ../goodwe-sems-home-assistant/custom_components/sems sems
   ```

4. **Install development dependencies:**
   ```bash
   pip install -r requirements.test.txt
   pip install ruff mypy
   ```

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

Create a descriptive branch name:
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
mypy custom_components/ --ignore-missing-imports --python-version 3.13
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

- Add docstrings to all public functions and classes
- Use clear, descriptive variable and function names
- Update README.md if your changes affect user-facing features
- Update `strings.json` for any UI text changes

## Testing

### Running Tests

**Run all tests:**
```bash
pytest tests/ -v
```

**Run with coverage:**
```bash
pytest tests/ --cov=custom_components.sems --cov-report=term-missing -v
```

**Run a specific test file:**
```bash
pytest tests/test_sems_api.py -v
```

**Run a specific test:**
```bash
pytest tests/test_sems_api.py::TestSemsApi::test_get_login_token_success -v
```

### Writing Tests

- Add tests for all new functionality
- Follow the existing test patterns in `tests/`
- Use `requests-mock` for mocking HTTP calls
- Ensure tests are isolated and don't depend on external services
- Aim for high code coverage (ideally >80%)

### Test Structure

Tests are organized as follows:
- `tests/test_sems_api.py` - API client tests
- `tests/test_sensor_entities.py` - Home Assistant entity tests
- `tests/fixtures.py` - Test data fixtures
- `tests/conftest.py` - Pytest configuration

See `tests/README.md` for more details.

## Submitting Changes

### Pull Request Process

1. **Update your fork:**
   ```bash
   git checkout main
   git pull upstream main
   ```

2. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

3. **Make your changes:**
   - Write code following the style guidelines
   - Add or update tests
   - Update documentation if needed

4. **Verify your changes:**
   ```bash
   # Run linting
   ruff check custom_components/
   ruff format --check custom_components/
   mypy custom_components/ --ignore-missing-imports --python-version 3.13
   
   # Run tests
   pytest tests/ -v
   ```

5. **Commit your changes:**
   ```bash
   git add .
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
- Reference any related issues (e.g., "Fixes #123")
- Include tests for new functionality
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

### Examples

```
feat(api): add support for multiple power stations

Add ability to configure and monitor multiple power stations
from a single integration instance.

Fixes #45
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
- Test coverage and passing tests
- Clear documentation and comments
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
