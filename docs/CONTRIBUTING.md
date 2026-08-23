# Contributing to LightBox

This describes how the code is put together and the rules a change has to follow.
Read [ARCHITECTURE.md](ARCHITECTURE.md) first for how the pieces fit.

Bug reports and pull requests are welcome at
<https://github.com/lightboxmissions/lightbox-public>.

## The rules that matter most

1. **The server is standard library only.** `app/server.py` and everything it imports
   must run on a plain Python 3 install with no `pip` packages. It runs on machines
   with no internet, where installing a dependency is not a small ask. The only
   pinned packages in `requirements.txt` are for the optional content tools in
   `tools/`, and the server never touches them.

2. **The server must keep working with pieces missing.** A machine may have no video
   lessons, no translator running, or no model loaded. Each of those degrades one
   feature. None of them may take the whole app down.

3. **Student data stays on the server.** Nothing may be sent off the machine. There
   is no telemetry, no analytics, and no outbound request outside install time.

4. **Content keeps its attribution.** Books carry their author, illustrator, source,
   and licence in their JSON. Those fields are a licence condition, not decoration.
   See [NOTICE.md](../NOTICE.md).

## Running it while you work

The server needs no build step. Edit a file and restart:

```bash
cd ~/lightbox
python3 app/server.py
```

It serves on port 8090. The model and translator are separate services, so if you
are only changing the interface you can leave them stopped; the pages load and only
the tutor and translations are unavailable.

## Text on screen and translation

Every string a user can read goes through the translation system. Never put a literal
string in HTML or JavaScript.

- The English text lives in one place: the `UI` dictionary in `app/server.py`. That
  is the source of truth.
- `/api/i18n?lang=` serves it, machine translating through LibreTranslate and caching
  the result to disk per language.
- In JavaScript, read a string with `t("key")`. In HTML, use `data-i18n="key"`, or
  `data-i18n-ph` for a placeholder and `data-i18n-aria` for an aria label.
- `app.js` has a `DEFAULTS` object holding the same English text, used if the
  translations have not loaded yet.

Adding a string means four things in the same change:

1. Add the key and the English text to `UI` in `app/server.py`.
2. Add the same key and identical text to `DEFAULTS` in `app/static/app.js`.
3. Reference it with `t("key")` or `data-i18n="key"`, never inline text.
4. **Bump `CACHE_VER` in `app/server.py`.** The cache file for each language is only
   rebuilt when it is missing entirely. Without a bump, French, German, and Spanish
   never see the new key and silently fall back to English.

Book titles, authors, teacher written test questions, and student names are content
rather than interface text, and are correctly left untranslated.

A screen that builds its text in JavaScript rather than from `data-i18n` attributes
must also be handled in `refreshScreenTexts()` in `app.js`, or its text will not
change when the language selector changes while that screen is open. Re-render only
the parts holding translated text; do not reset what the student was in the middle
of doing.

Before calling a change done, check that every key used with `t(...)` or `data-i18n`
exists in `UI`, and that every key read with `t()` also has a `DEFAULTS` entry.

## Front-end assets

`app/static/style.css` and `app/static/app.js` are loaded with a version query, for
example `style.css?v=70`. Bump that number in `index.html` and `teacher.html` when
you change either file, or tablets keep serving the copy they already cached.

## Design system

`app/static/style.css` opens with a `:root` block defining the whole vocabulary:
the navy, gold, and cream palette, three font roles, a seven step type scale, and a
four pixel spacing scale. The rest of the file uses only those variables.

New interface should reuse an existing token and an existing component class. A raw
hex colour or a one off pixel value is how the design drifts apart.

The three font roles are Baloo 2 for headings, titles, card labels, and buttons;
Lexend for body text, metadata, and inputs; Literata for story text inside the book
reader only.

## Tests

```bash
cd app
python3 -m unittest discover -s tutor_core/tests -t .
```

`app/tutor_core/` is a self-contained maths engine and answer checker with its own
test suite. It is a library in the repository: `app/server.py` does not import it,
and questions asked through the app go to the language model. If you are changing how
answers are produced, that is the code to be aware of.

## Commit messages

Say what the change does and why, in plain language. One line summary, then detail
if it needs it.

## Adding a lesson

1. Put `content/<CODE>.mp4` and `content/<CODE>.srt` in place.
2. Add the entry to `data/catalog.json` with its id, title, topic, and duration.
3. Run `python3 app/prep.py` to build the plain text transcript the tutor reads.
4. Add a quiz for it in `data/quizzes.json`, keyed by the same code.

## Adding a book

Each book is a folder under `books/` holding its images and one JSON file per
language. Copy the shape of an existing book, including the `author`, `illustrator`,
`source`, `source_url`, `license`, and `license_url` fields. A book without those
cannot be shipped, because the licence requires the credit to travel with it.
