# Horilla CRM product brochures

Self-contained HTML product brochures for print and PDF. These are **not** Django templates — open them in a browser; do not serve them through the app.

| File | Use |
|------|-----|
| [horilla_crm_brochure_short.html](horilla_crm_brochure_short.html) | Short / overview brochure |
| [horilla_crm_brochure_detail.html](horilla_crm_brochure_detail.html) | Detailed brochure |

Titles currently reference **v1.17.2**; update the HTML `<title>` and body copy when you produce a new release brochure.

## Open in a browser

From the repo root:

```bash
# Windows (PowerShell)
start docs/brochures/horilla_crm_brochure_short.html
start docs/brochures/horilla_crm_brochure_detail.html
```

Or open the files directly from File Explorer / Finder.

An internet connection is needed the first time so Google Fonts can load (Syne, IBM Plex).

## Print to PDF

1. Open the brochure HTML in Chrome, Edge, or Firefox.
2. **Print** (`Ctrl+P` / `Cmd+P`).
3. Destination: **Save as PDF** (or Microsoft Print to PDF).
4. Recommended settings:
   - Paper: **A4** (brochures use `@page { size: A4 }`)
   - Margins: **None** / default as designed
   - Background graphics: **On** (colors and brand fills)
   - Scale: **100%** / Default

Save next to the HTML or under a dated release folder if you keep PDF archives outside git.

## Notes

- Keep brochures under `docs/brochures/` only — not under `templates/` or app packages.
- Developer architecture docs stay in `docs/horilla/` and `docs/horilla_crm/`.
- Weekly prose release notes stay in `release.md` / `CHANGELOG.md` at the repo root; link here if needed.
