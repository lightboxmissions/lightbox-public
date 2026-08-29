# Lunis Reading Section — Open-Licensed Children's Books

Offline library of openly-licensed (Creative Commons) children's storybooks for the Lunis
reading section. English and French first. Downloaded 2026-06-23.

## What's here

| Source | Folder prefix | Books | Languages | Origin | License |
|---|---|---|---|---|---|
| African Storybook Project | `asp_*` | 30 | English + French | africanstorybook.org, via [global-asp/asp-source](https://github.com/global-asp/asp-source) + `asp-imagebank` | CC BY 4.0 / CC BY-NC 4.0 |
| Pratham Books / StoryWeaver | `pb_*` | 25 | English | storyweaver.org.in, via [global-asp/pb-source](https://github.com/global-asp/pb-source) + `pb-imagebank` | mostly CC BY 4.0 |
| Global Digital Library | — | 0 | — | — | **NOT downloaded — see below** |

Totals: **55 stories**, **85 book-language files** (55 EN + 30 FR), **510 illustrations**, ~32 MB.
License split: **78 CC BY**, **7 CC BY-NC**.

### Global Digital Library status
GDL's documented public API host (`api.digitallibrary.io`) **no longer resolves in DNS** — their
programmatic API appears to be offline or migrated (the reader site at content.digitallibrary.io is
still up). It could not be fetched cleanly. Revisit when the API/OPDS feed is restored, or extract
from their ePub downloads manually. The African Storybook + Pratham/StoryWeaver sources cover the
same early-grade English/French need in the meantime.

## Folder layout

```
books/
  credits.json            <- master attribution index (every book-language entry)
  README.md               <- this file
  asp_0176/               <- one folder per story
    01.jpg ... 13.jpg      <- illustrations, one per spread (shared across languages)
    en.json                <- English text + metadata
    fr.json                <- French text + metadata (if available)
  pb_0002/
    01.jpg ... 08.jpg
    en.json
```

## Per-book JSON schema (`en.json` / `fr.json`)

```json
{
  "id": "asp_0176",
  "language": "en",
  "title": "Listen",
  "source": "African Storybook Project (via Global ASP)",
  "source_url": "https://github.com/global-asp/asp-source/blob/master/en/0176_listen.md",
  "project_home": "https://www.africanstorybook.org",
  "license": "CC BY-NC",
  "license_raw": "CC-BY-NC",
  "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
  "author": "Carole Bloch",
  "illustrator": "Jean Fullalove",
  "translator": "Claire Sjaarda, Translators without Borders",
  "images": ["01.jpg", ...],
  "pages": ["Crickets chirp.", "Mice squeak.", ...]
}
```

**Spread pairing:** `images[0]` is the cover (show with `title`); spread *i* pairs `images[i]` with
`pages[i-1]`. (Illustrations are shared across languages — only `pages`/`title`/`translator` differ.)

## Attribution & licensing (display these on screen)

Every book MUST be shown with credit: **author** (`Text`), **illustrator** (`Illustration`),
**translator** where present, the **source/project**, and the **license** (link `license_url`).
`credits.json` aggregates all of this for easy rendering.

- **CC BY** — free to use/adapt with attribution.
- **CC BY-NC** (7 books) — attribution + **non-commercial use only**. Fine for this free educational
  app; do not sell or use commercially.

## Deploying to the server

Copy this `books/` folder to the box (e.g. `~/lunis/books/`) and have `server.py` serve it (new
route) so the website can render the reading section. (Implementation per the next instructions.)
