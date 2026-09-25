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
5. Identify the previous **non-beta** release tag first. Update
   [RELEASE_NOTES.md](../../../RELEASE_NOTES.md) with every user-visible change
   since that stable tag, including changes introduced by intermediate beta
   tags. Compare the full commit range (for example, `git log
   <previous-stable>..<new-version>`) rather than only the immediately
   previous beta. Group related changes by capability and include important
   limitations or compatibility notes.
6. Record every contributor in the release entry using their GitHub handle:
   - Attribute code contributions to the authors of the relevant commits or pull requests.
   - Attribute information, testing, or troubleshooting contributions to the users who provided them in issues, discussions, or pull requests.
   - Verify handles from GitHub rather than inferring them from commit email addresses.
7. Copy the completed release entry into the GitHub Release description.

## Validation

- Run the narrowest relevant tests before releasing.
- Run `ruff check` and `ruff format --check` for the touched area if code changed.
- Confirm the manifest version matches the tag and release metadata.

## Notes

- Keep [RELEASE_NOTES.md](../../../RELEASE_NOTES.md) as the source of truth, with one entry per release and a contributor list under each entry.
- For a stable release promoted from beta, preserve the complete beta history
  in the stable entry and explicitly summarize all changes since the previous
  non-beta release.
- Keep release notes concise and focused on user-visible changes.
- For pre-releases, make the beta/pre-release state explicit in both the version and the GitHub Release settings.
