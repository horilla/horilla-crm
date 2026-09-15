# Changelog

All notable changes to Horilla CRM are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file starts at **1.13.8**, the first release maintained in this format. Releases
before it are documented on the
[releases page](https://github.com/horilla/horilla-crm/releases) and are not reproduced
here — they predate this convention and back-filling them would misrepresent how they
were recorded at the time.

Each released version corresponds to a git tag of the same name (bare semver, no `v`
prefix) and to the Docker tag `horilla/horilla-crm:<version>`. `horilla/__version__.py`
is the single source of truth for the **whole CRM product** version (not only the
`horilla/` package directory); the release workflow refuses to publish an image whose
tag disagrees with it. See [docs/versioning.md](docs/versioning.md).

Horilla CRM also versions its applications independently — each app carries its own
`__version__.py`, surfaced together by `horilla/utils/version.py`. Those app versions
move on their own cadence and are not tracked in this file.

## [Unreleased]

<!--
Add entries here as you merge, under the headings below. Drop any heading you
do not use. At release time, rename this section to the new version with its
date and open a fresh Unreleased above it.

### Breaking      — requires action from an existing installation before or on upgrade
### Added         — new features
### Changed       — changes to existing behaviour
### Deprecated    — soon-to-be-removed features
### Removed        — features removed in this release
### Fixed         — bug fixes
### Security      — vulnerabilities fixed; link the advisory and credit the reporter
-->

### Added

- **Form Layouts app** — administrators can choose, per company, which fields appear on
  the Lead and Opportunity create forms and in what order. Once a layout is saved, the
  create button opens a trimmed single-page form; edit forms are unchanged.

## [1.13.8] — 2026-09-05

### Added

- **Field Requirements app** — administrators can configure required and optional fields
  per company for supported CRM models such as Leads and Opportunities.
- Granted-access permission framework: users explicitly granted access to a record can
  act on it according to their assigned permissions without being the owner.
- Opportunity Team permissions gain dedicated read, edit and owner-level handling.
- Shared UI components: My Settings shell, empty-state components, active toggle.

### Changed

- Streaming-based CSV, XLSX and PDF exports.
- Database indexes added on frequently filtered and grouped fields; forecast period
  matching optimised; company list cached.

### Fixed

- Forecast pagination, history rendering, authentication fixes, and Exotel and Outlook
  integration error handling.

### Upgrading

```bash
docker pull horilla/horilla-crm:1.13.8
```

[Unreleased]: https://github.com/horilla/horilla-crm/compare/1.13.8...HEAD
[1.13.8]: https://github.com/horilla/horilla-crm/releases/tag/1.13.8
