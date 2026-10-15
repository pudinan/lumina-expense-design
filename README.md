# Lumina Expense — Design

Static HTML mockups of the Lumina Expense product (Terra TDV / Terra Digital Ventures).

## Pages

`index.html` is a single self-contained file with a tab bar to switch between the 3 pages:

- **Desktop** — full Desktop user flows
- **Mobile** — full Mobile user flows
- **Employee expense policy** — the Employee detail page with the Expense Policy feature

Each page has its own link: `index.html#desktop`, `index.html#mobile`, `index.html#policy`.

## Navigating

| Action | How |
|---|---|
| Zoom toward the cursor | Trackpad pinch, or Ctrl/⌘ + scroll |
| Zoom in / out / reset | Ctrl/⌘ + `=` / `−` / `0`, or the − / % / + controls |
| Pan | Hold Space and drag, drag with the middle mouse button, or the hand tool (`H` on, `V` / `Esc` off) |

Zoom is remembered per page in the browser.

## Deployment

Upload `index.html` to any static host — it has no other files and needs no server-side code.

```bash
# GitHub Pages: Settings → Pages → Deploy from branch → main → / (root)

# Or any static server
python3 -m http.server 8080   # then open http://localhost:8080
```

React 18.3.1 is embedded in the file. Only the Poppins / Sarabun fonts and Material Symbols icons load from Google Fonts; without internet the page still works, with system fonts and icon names shown as text.

If the host sets a Content-Security-Policy, it must allow inline scripts, `blob:` frames, and `fonts.googleapis.com` / `fonts.gstatic.com`.

## Updating from Claude Design

Source of truth is Claude Design project `94f51a5b-ae22-4581-a0aa-b996e41cc749`.

1. Download the project from Claude Design and unzip it.
2. Rebuild:

   ```bash
   python3 -I build.py "<path to unzipped project>"
   ```

3. Commit `index.html` and push.

`build.py` inlines `Desktop.dc.html`, `Mobile.dc.html` and `Employee detail - expense policy.dc.html` with the design-system CSS/JS, the runtime (`support.js`), the Terra logos and React from `vendor/`. It checks the vendored React files against the hashes pinned in `support.js` and stops if they don't match. It needs macOS (`sips` resizes the logos).
