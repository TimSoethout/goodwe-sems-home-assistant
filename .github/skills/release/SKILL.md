---
name: release
description: "Use when managing HACS releases for this integration, including version bumps, tags, beta/pre-release publishing, and release notes."
---

# Release Workflow

Use this skill when preparing a HACS release for the SEMS integration.

## Steps

1. Update the semantic version in [custom_components/sems/manifest.json](../../../custom_components/sems/manifest.json).
2. Choose the next stable version from the latest stable release, ignoring pre-releases when choosing its version number:
   - Increment `PATCH` for backward-compatible bug fixes.
   - Increment `MINOR` for backward-compatible features.
   - Increment `MAJOR` for breaking changes, such as incompatible entity or configuration behavior.
3. For beta releases, use the version of the intended stable release plus a numbered pre-release suffix, such as `11.12.0-beta.1`, `11.12.0-beta.2`. Keep the same `MAJOR.MINOR.PATCH` for every beta in that release stream. A beta is not a stable release and does not consume that version number.
   - Example: after stable `11.11.0`, a backward-compatible change can be tested as `11.12.0-beta.1` and released as stable `11.12.0`.
   - If a beta includes a breaking change, target the next major instead: `12.0.0-beta.1`, then stable `12.0.0`.
   - Do not use spaces or append `RC` to the version. If a release candidate is needed, use a valid suffix such as `-rc.1`; otherwise keep using `-beta.N`.
4. Create a git tag matching the manifest version, for example `11.12.0-beta.1` or `11.12.0`. Do not reuse published version tags.
5. Publish a GitHub Release for that tag. Mark beta releases as **pre-release** so HACS users who opt into pre-releases can receive them; publish the final version as a regular release. This triggers `.github/workflows/release.yml`, which uploads the integration ZIP. Tags alone are not enough for HACS.
6. Identify the previous **non-beta** release tag first. Update
   [RELEASE_NOTES.md](../../../RELEASE_NOTES.md) with every user-visible change
   since that stable tag, including changes introduced by intermediate beta
   tags. Compare the full commit range (for example, `git log
   <previous-stable>..<new-version>`) rather than only the immediately
   previous beta. Keep each item clear and concise, describing the user-visible
   change rather than implementation details. Preserve existing issue and pull
   request links, and include the relevant link when available; never invent one.
   Group related changes by capability and include important limitations or
   compatibility notes.
7. Record every contributor in the release entry using their GitHub handle:
   - Attribute code contributions to the authors of the relevant commits or pull requests.
   - Attribute information, testing, or troubleshooting contributions to the users who provided them in issues, discussions, or pull requests.
   - Verify handles from GitHub rather than inferring them from commit email addresses.
8. Copy the completed release entry into the GitHub Release description.

## Validation

- Run the narrowest relevant tests before releasing.
- Run `ruff check` and `ruff format --check` for the touched area if code changed.
- Confirm the manifest and GitHub release tag match, the pre-release setting is correct, and the release ZIP was uploaded.

## Notes

- Keep [RELEASE_NOTES.md](../../../RELEASE_NOTES.md) as the source of truth, with one entry per release and a contributor list under each entry.
- For a stable release following betas, use the same `MAJOR.MINOR.PATCH` as the beta stream. Preserve the complete beta history in the stable entry and summarize all changes since the previous stable release.
- Keep release notes concise and focused on user-visible changes; retain issue and pull request links when carrying items forward or editing notes.
- HACS users must enable the repository's pre-release switch to receive beta updates; keep stable releases regular so users who have not opted in stay on stable versions.
