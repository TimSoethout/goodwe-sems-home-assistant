---
name: release
description: "Use when managing HACS releases for this integration, including version bumps, tags, beta/pre-release publishing, and release notes."
---

# Release Workflow

Use this skill when preparing a HACS release for the SEMS integration.

## Steps

1. Update the semantic version in [custom_components/sems/manifest.json](../../../custom_components/sems/manifest.json).
2. For beta releases from branches, use the `x.x.x-beta` version format and mark the GitHub Release as a Pre-release.
3. Create a git tag for the new version: `x.x.x(-beta)`.
4. Publish a GitHub Release for that tag. Tags alone are not enough for HACS; the latest release tag is what remote version checks use.
5. Write release notes that summarize the changes since the previous release, ideally based on commits since the prior tag.

## Validation

- Run the narrowest relevant tests before releasing.
- Run `ruff check` and `ruff format --check` for the touched area if code changed.
- Confirm the manifest version matches the tag and release metadata.

## Notes

- Keep release notes concise and focused on user-visible changes.
- For pre-releases, make the beta/pre-release state explicit in both the version and the GitHub Release settings.
