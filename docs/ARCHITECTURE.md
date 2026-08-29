# How Lunis works

A tour of the moving parts, so you can change things with confidence. For the *why*
behind conventions, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Big picture

```
Browser (index.html + app.js + style.css)
      │  fetch() JSON + stream video/captions
      ▼
app/server.py  ── a single Python HTTP server (stdlib http.server) ──┐
      │                                                              │
      ├─ serves static files and the two HTML pages                  │
      ├─ reads lesson data from data/*.json (loaded once at startup) │
      ├─ streams video/captions from content/                        │
      ├─ calls llama.cpp  for AI answers + open-quiz grading  ───────┤ localhost
      └─ calls LibreTranslate for non-English UI/quiz/captions ──────┘
```

Everything is a flat file. There is **no database** — student results are one JSON file
per student under `data/progress/`, and translation results are cached as JSON/VTT files
under `data/`.

## The backend: `app/server.py`

One file, pure standard library. Its shape:

1. **Config** (top of file) — resolves each setting from `LIGHTBOX_<KEY>` env var →
   `config.json` → built‑in default. Ports, model name, and the two service URLs live
   here.
2. **Data load at startup** — `catalog.json`, `notes.json`, `quizzes.json` are read once
   into memory (`CATALOG`, `NOTES`, `QUIZZES`). **Because of this, you must restart the
   server after editing those files.**
3. **`GRADES` / `VALID_GRADES`** — map each lesson code to a grade (K–8).
4. **Request handler** — a `BaseHTTPRequestHandler` with a big `do_GET`/`do_POST` route
   table (search for `if path ==` / `path.startswith`). Key routes:
   - `GET /` and `/teacher` → the two HTML pages
   - `GET /api/catalog`, `/api/i18n`, `/api/quiz/<code>` → lesson data (localized)
   - `GET /api/video/<code>`, `/api/subs/<code>` → media (with HTTP range support)
   - `POST /api/ask` → streamed AI answer (Server‑Sent Events)
   - `POST /api/grade` → grade a quiz (MC deterministically, open‑ended via the model)
   - `POST /api/login`, `/api/progress/...` → student identity + saved results
   - `/api/teacher/...` → the admin dashboard (needs the teacher password)
5. **Translation layer** — anything non‑English is translated through LibreTranslate and
   **cached to disk** so it's instant next time. English is always the source of truth;
   the AI reasons in English even when the child sees another language.
6. **Concurrency** — a `ThreadingHTTPServer`, plus rate‑limiting so a burst of student
   devices queues rather than overwhelming the weak CPU. Page/lesson/quiz responses are
   always cache‑first and never block on translation.

## The front‑end: `app/static/`

Plain HTML/CSS/JS — no build step, no framework.

- **`index.html`** — the student app shell. Text that gets translated is marked with
  `data-i18n="key"` attributes.
- **`app.js`** — all student behaviour: sign‑in, browsing lessons by grade→topic, the
  video player, the Ask tab (calls `/api/ask`), the Quiz tab, progress, and the language
  picker. On load it fetches `/api/i18n?lang=…` and fills every `data-i18n` element.
- **`style.css`** — all styling, and the design system itself: the `:root` block at the
  top defines the palette, the 7-step type scale, the 4px spacing scale, and three font
  roles, and everything below only consumes those variables. Rules for using it:
  [CONTRIBUTING.md → Design system](CONTRIBUTING.md#design-system).
- **`teacher.html`** — the separate teacher/admin dashboard (student list, progress,
  custom tests, settings). Self-contained: its own inline script and styles, sharing only
  `style.css`, so a student-app change can't break the teacher's screen.
- **`fonts/`** — three self-hosted families, no CDN, because the box is offline:
  **Baloo 2** (headings, buttons, nav), **Lexend** (body and inputs — the app-wide
  default, chosen for reading ease for developing readers), **Literata** (story text
  inside the e-book reader only). Each family ships `latin` *and* `latin-ext` `.woff2`
  files per weight, split on the vendor's own `unicode-range`, so accented French/German/
  Spanish characters render from the right file instead of falling back to a system font.

## Accounts, classes and sessions

Students and teachers sign themselves up; there is no central account server. It's all
flat files under `data/`, written at runtime and never committed:

| File | Role |
|---|---|
| `users/<name>.json` | One per account — role, password hash, class membership. |
| `classes/<id>.json` | One per class — roster, join code, pending approvals. |
| `classes_index.json` | Lookup from join code to class id. |
| `sessions.json` | Live sign-in tokens (the browser holds one in `localStorage`). |
| `tests/`, `notifications.json`, `test_archive.json` | Teacher-built tests and their results — these carry real student names. |

A student joins a class by typing its **join code**; the teacher approves the request from
the dashboard. The teacher dashboard itself is gated by the teacher key from
`config.json` / the first-run wizard.

## The verified-answer pipeline: `app/tutor_core/`

A standalone package (pure stdlib, its own tests) that enforces one rule: **the model
never has final authority over a number.** Computational questions get their answer from a
deterministic evaluator *before* any inference; conceptual questions go to the model, and
any arithmetic inside the explanation is checked afterwards. It also detects the machine's
hardware tier and queues students when there are more askers than slots.

**Status: not wired in yet.** `server.py` does not import it and the deploy script does
not ship it — today it runs standalone (`python3 -m tutor_core.service --port 8091`) while
`server.py` still calls llama.cpp directly. See [`app/tutor_core/README.md`](../app/tutor_core/README.md)
for the module map, the tier table, and the benchmark harness.

## Internationalization (i18n)

- The **English source** strings live in a `UI = {…}` dict inside `server.py`.
- For other languages, `server.py` runs that dict through LibreTranslate once and caches
  it as `data/i18n_<CACHE_VER>_<lang>.json`.
- The browser calls `/api/i18n?lang=fr` and sets each `data-i18n` element's text.
- `CACHE_VER` (top of `server.py`) is a cache‑buster: bump it to throw away stale
  translation caches and rebuild.
- **Never translate bare math** (`1/2` etc.) — the server already skips strings with no
  real word; keep it that way.

## Data files (`data/`)

| File | Role |
|---|---|
| `catalog.json` | The master lesson list. Each entry: `id` (code), `yt`, `title`, `full_title`, `topic`, `topic_label`, `duration_min`, `video`, `transcript`. |
| `notes.json` | A short note per lesson — the AI's context when answering questions (kept short for speed instead of the full transcript). |
| `quizzes.json` | Per‑lesson quiz: one multiple‑choice question and one open‑ended question with grading hints. |
| `progress/<name>.json` | One file per student: which lessons/quizzes they've done and scored. Written at runtime. |
| `subs/*.vtt` | Cached translated captions. Written at runtime. |
| `setup.json` | Saved by the first‑run wizard (teacher password + default language). |

Lesson **codes** are a topic‑letter prefix + number (e.g. `CO`=counting, `PV`=place
value, `AS`=add/subtract, `FR`=fractions, …). The front‑end groups lessons by that
prefix automatically, so a new prefix forms a new topic group on its own.

## Content included

The repo now carries the **full production content**, in sync with the box:

- **127 math lessons, grades K–8** — videos + captions in `content/`, transcripts in
  `transcripts/`, and `data/catalog.json` / `notes.json` / `quizzes.json`.
- **44 unit tests** — `data/unit_tests.json`.
- **85 reading books** — `books/<id>/{en,fr,es,de}.json` + page images, with pre‑built
  book quizzes in `data/bookquiz/`.

So a fresh clone (or a server built with `server/install.sh`) serves the same lessons,
tests, and books the reference box does. Runtime data (student progress, translation
caches) is still generated locally and stays out of git.
