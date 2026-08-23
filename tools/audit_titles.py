#!/usr/bin/env python3
"""Report book titles that silently fell back to English.

translate_book() writes <lang>.json even when the title translation failed, so a
book can have fully translated pages and an English title - gb43/es sat that way
unnoticed. This lists every book whose translated title is byte-identical to the
English one, minus the cases where that is correct: titles published under the
original name (Heidi, Peter Pan, Oliver Twist) are marked "published" in
data/book_titles.json and are not reported.

    python3 tools/audit_titles.py
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = os.environ.get("LIGHTBOX_BOOKS") or os.path.join(ROOT, "books")
TABLE = os.path.join(ROOT, "data", "book_titles.json")
LANGS = ("fr", "es", "de")


def load(fp):
    with open(fp, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    curated, ok_list = {}, {}
    if os.path.exists(TABLE):
        tbl = load(TABLE)
        curated = {k: v for k, v in tbl["titles"].items() if isinstance(v, dict)}
        ok_list = {k: v for k, v in tbl.get("identical_ok", {}).items() if isinstance(v, list)}
    suspect, ok_same, total = [], 0, 0
    for bid in sorted(os.listdir(BOOKS)):
        en_fp = os.path.join(BOOKS, bid, "en.json")
        if not os.path.isdir(os.path.join(BOOKS, bid)) or not os.path.exists(en_fp):
            continue
        en = load(en_fp).get("title", "").strip()
        for lang in LANGS:
            fp = os.path.join(BOOKS, bid, lang + ".json")
            if not os.path.exists(fp):
                continue
            total += 1
            got = load(fp).get("title", "").strip()
            if got != en:
                continue
            # identical on purpose: the curated table says this language publishes
            # the book under its original title
            if curated.get(bid, {}).get(lang, "").strip() == en or lang in ok_list.get(bid, []):
                ok_same += 1
                continue
            suspect.append((bid, lang, en))
    print("checked %d translated titles across %s" % (total, "/".join(LANGS)))
    print("identical to English on purpose (published under original name): %d" % ok_same)
    print("\nSUSPECT - translated title is still the English one:")
    if not suspect:
        print("  none")
    for bid, lang, en in suspect:
        print("  %-10s %s  %r" % (bid, lang, en))
    return 1 if suspect else 0


if __name__ == "__main__":
    sys.exit(main())
