---
name: release
description: "Use when preparing HACS releases, versions, tags, or release notes."
---

# HACS Release

1. **Version:** Update `custom_components/sems/manifest.json`. Base the next stable version on the latest stable release: patch for fixes, minor for features, major for breaking changes. Use numbered prereleases (for example, `11.12.0-beta.1`) for the intended stable version; breaking beta changes target the next major. Never reuse a published tag.
2. **Release notes:** Update [RELEASE_NOTES.md](../../../RELEASE_NOTES.md) with all user-visible changes since the previous stable tag, including every beta. Keep notes concise; preserve existing links, add verified links when available, and never invent them. Include limitations and compatibility notes.
3. **Contributors:** Credit code authors and people who contributed information, testing, or troubleshooting. Verify GitHub handles; do not infer them from email addresses.
4. **Publish:** Tag with the manifest version and publish a GitHub Release. Mark betas as prereleases; stable releases are regular releases. Copy the release notes into the release description. Publishing triggers `.github/workflows/release.yml` to upload the ZIP; a tag alone is insufficient.

For a stable release after betas, use the same version number and preserve the full beta history in its notes. HACS users must opt into prereleases to receive betas.

## Before finishing
- Run the narrowest relevant tests; if code changed, run `ruff check` and `ruff format --check` on the touched area.
- Confirm manifest/tag versions match, prerelease status is correct, and the ZIP uploaded.
