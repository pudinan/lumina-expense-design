# Lumina Expense — Design

Static HTML mockups of the Lumina Expense product (Terra TDV / Terra Digital Ventures).

## Pages

Open `index.html` in a browser — it tabs between the 3 standalone pages:

- **Desktop** — full Desktop user flows
- **Mobile** — full Mobile user flows
- **Employee · Expense Policy** — the Employee detail page with the new Expense Policy feature (Advisory / Product Owner / No Policy)

Each page is a self-contained HTML export from [Claude Design](https://claude.ai/design).

## Deployment

Drop the two files (`index.html` and `latest/`) on any static host:

```bash
# GitHub Pages (recommended)
# Settings → Pages → Deploy from branch → main → / (root)

# Or any static server
python3 -m http.server 8080   # then open http://localhost:8080
```

## Source

Source of truth lives in Claude Design project `94f51a5b-ae22-4581-a0aa-b996e41cc749`. To update: re-export from Claude Design, replace files in `latest/`, commit, push.
