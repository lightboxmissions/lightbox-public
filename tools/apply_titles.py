#!/usr/bin/env python3
"""Apply the curated published titles in data/book_titles.json to the book JSON.

Machine translation renders a classic's title literally, which produces titles no
reader of that language would recognise ("Fang blanc" for White Fang). The curated
table holds the title each book was actually published under; this script writes it
into books/<id>/<lang>.json, leaving every other field - including the translated
page text - untouched.

Safe to re-run: it only writes when the stored title differs, and it refuses to
touch a book whose English title no longer matches the table (a sign the catalogue
moved on and the curated entry is stale).

    python3 tools/apply_titles.py            # report what would change
    python3 tools/apply_titles.py --write    # write it
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# LIGHTBOX_BOOKS points the script at another books/ tree - used to apply the same
# titles to the staging copy that gets pushed to the server as well as to the repo
BOOKS = os.environ.get("LIGHTBOX_BOOKS") or os.path.join(ROOT, "books")
TABLE = os.path.join(ROOT, "data", "book_titles.json")
LANGS = ("fr", "es", "de")


def load(fp):
    with open(fp, encoding="utf-8-sig") as f:
        return json.load(f)


def main(write):
    table = {k: v for k, v in load(TABLE)["titles"].items() if isinstance(v, dict)}
    changed = skipped = missing = 0
    for bid in sorted(table):
        want = table[bid]
        en_fp = os.path.join(BOOKS, bid, "en.json")
        if not os.path.exists(en_fp):
            print("MISSING  %s (no en.json)" % bid); missing += 1; continue
        # guard against a stale curated entry: if the English title changed, the
        # translations in the table may belong to a different edition/book
        en_title = load(en_fp).get("title", "")
        if en_title.strip() != want["en"].strip():
            print("STALE    %s: en is %r, table expects %r - skipping"
                  % (bid, en_title, want["en"])); skipped += 1; continue
        for lang in LANGS:
            fp = os.path.join(BOOKS, bid, lang + ".json")
            if not os.path.exists(fp):
                print("MISSING  %s/%s" % (bid, lang)); missing += 1; continue
            b = load(fp)
            old = b.get("title", "")
            new = want[lang]
            if old == new:
                continue
            print("%-8s %s  %r -> %r" % (bid, lang, old, new))
            changed += 1
            if write:
                b["title"] = new
                # the title is curated by hand now, so record that it is not the
                # machine output the rest of the file still is
                b["title_source"] = "published"
                with open(fp, "w", encoding="utf-8") as f:
                    json.dump(b, f, ensure_ascii=False)
    print("\n%s: %d title(s) %s, %d skipped, %d missing"
          % ("WROTE" if write else "DRY RUN", changed,
             "written" if write else "would change", skipped, missing))
    return 0


if __name__ == "__main__":
    sys.exit(main("--write" in sys.argv))
