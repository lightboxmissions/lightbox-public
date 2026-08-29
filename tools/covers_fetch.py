#!/usr/bin/env python3
"""Re-source high-resolution covers for the public-domain classics.

The covers shipped with the books came from Gutenberg's `pgNNNN.cover.medium.jpg`,
which tops out at 200px wide - four of them are barely 65px. A shelf thumbnail is
152 CSS px, which is 304 device px on a 2x screen, so every one of them renders soft.
Gutenberg has no larger size, so the art has to come from somewhere else.

Sources, in order, all recorded per book so the licensing stays auditable:
  1. Open Library covers API (-L, typically 500-1000px)
  2. Google Books (thumbnail URL bumped to zoom=3)
  3. a generated cover in Lunis's own design language - Baloo 2 title on the
     app's cream/navy, which beats a blurry scan

Everything is normalised to a 2:3 portrait at 600x900 so the shelf grid is uniform,
and written to books/<id>/cover.jpg with the source recorded in books/<id>/cover.json.

This runs on a machine with internet (the server has none), then the covers are
copied across.

    python3 tools/covers_fetch.py --list          # what would be fetched
    python3 tools/covers_fetch.py --write         # fetch + write
    python3 tools/covers_fetch.py --write --only gb43,gb76
"""
import io, json, os, re, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOKS = os.environ.get("LIGHTBOX_BOOKS") or os.path.join(ROOT, "books")
TABLE = os.path.join(ROOT, "data", "book_titles.json")
TARGET_W, TARGET_H = 600, 900          # 2:3, matches .book-cover's aspect-ratio
# Never upscale: a source narrower than the target is exactly the blur we are trying
# to get rid of. Anything under this goes to the generated cover instead.
MIN_SOURCE_W = 600
# A front-cover scan is roughly 2:3 (0.67). Anything much wider is a spine+cover or a
# two-page spread, which cannot be cropped to a cover without losing the title.
PORTRAIT_LO, PORTRAIT_HI = 0.56, 0.78
# Wikimedia rejects generic agents ("does not comply with our robot policy"); their
# policy wants a named client with a contact URL, so this carries the project repo.
UA = {"User-Agent": "LunisCovers/1.0 (+https://github.com/lightboxmissions/Lunis) urllib/py3"}

# Lunis palette, straight from style.css
CREAM, NAVY, GOLD = (255, 248, 227), (22, 35, 59), (252, 196, 25)


# Python's bundled roots can be stale (Commons fails with "certificate has expired"
# against them); certifi ships a current bundle, so prefer it when it is installed.
def _ssl_ctx():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = _ssl_ctx()


def get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as r:
        return r.read()


def get_json(url, timeout=30):
    return json.loads(get(url, timeout).decode("utf-8", "replace"))


def open_library(title, author):
    """Every cover Open Library has for this work, best-scanned first.

    One work has many editions and their scan quality varies wildly - the first hit
    is often a 300px paperback while a later one is a 900px scan - so this yields all
    the candidates and lets the caller keep the largest.
    """
    q = urllib.parse.urlencode({"title": title, "author": author, "limit": 10})
    try:
        docs = get_json("https://openlibrary.org/search.json?" + q).get("docs", [])
    except Exception as e:
        print("      openlibrary search failed: %s" % e); return []
    out = []
    for d in docs:
        if d.get("cover_i"):
            out.append(("openlibrary",
                        "https://covers.openlibrary.org/b/id/%d-L.jpg" % d["cover_i"],
                        "Open Library cover_i=%d (%s)" % (d["cover_i"], d.get("key", ""))))
    return out


# Words that mean the file is about the book's world rather than being its cover:
# author portraits, house museums, statues, maps, and back covers all match a
# keyword search happily and are all wrong.
REJECT = ("back cover", "spine", "portrait", "photograph", "house", "room",
          "statue", "monument", "bust", "grave", "plaque", "map", "signature",
          "postage", "stamp", "poster", "playbill", "sheet music")
# too common to carry any signal about *which* book this is
STOP = {"the", "a", "an", "of", "and", "or", "in", "on", "at", "to", "de", "his", "her", "its"}


def title_words(s):
    return [w for w in re.split(r"[^a-z0-9]+", s.lower()) if w and w not in STOP]


def plausible(file_title, book_title):
    """Is this Commons file actually this book's cover?

    A keyword search returns anything sharing an author: Huckleberry Finn matched
    "Billiard Room - Mark Twain House", White Fang matched "Before Adam", and Anne of
    Green Gables matched its own sequel. Requiring EVERY content word of the book's
    title to appear in the file name rejects all of those, including the near-miss
    cases ("The Return of Sherlock Holmes" lacks "adventures") that a percentage
    threshold would have let through.
    """
    low = file_title.lower()
    if any(bad in low for bad in REJECT):
        return False
    want = title_words(book_title)
    if not want:
        return False
    have = set(title_words(file_title))
    return all(w in have for w in want)


def wikimedia(title, author):
    """First-edition/original cover art on Commons - the highest-resolution and the
    only source whose licence is stated on the file itself."""
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": "%s %s cover" % (title, author), "gsrlimit": 8,
        "gsrnamespace": 6, "prop": "imageinfo", "iiprop": "url|size",
        "iiurlwidth": 1200})
    try:
        data = get_json("https://commons.wikimedia.org/w/api.php?" + q)
    except Exception as e:
        print("      wikimedia search failed: %s" % e); return []
    pages = (data.get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        name = p.get("title", "")
        if not plausible(name, title):
            continue                       # right author, wrong book - see plausible()
        for ii in p.get("imageinfo") or []:
            url = ii.get("thumburl") or ii.get("url")
            if url and ii.get("width", 0) >= MIN_SOURCE_W:
                out.append(("wikimedia", url, "Commons: " + name))
    return out


def google_books(title, author):
    q = urllib.parse.urlencode(
        {"q": 'intitle:"%s" inauthor:"%s"' % (title, author), "maxResults": 5})
    try:
        items = get_json("https://www.googleapis.com/books/v1/volumes?" + q).get("items", [])
    except Exception as e:
        # unauthenticated Google Books rate-limits hard (429); it is the last resort
        # anyway, so a failure here just falls through to the generated cover
        print("      google books search failed: %s" % e); return []
    out = []
    for it in items:
        links = (it.get("volumeInfo") or {}).get("imageLinks") or {}
        url = links.get("thumbnail") or links.get("smallThumbnail")
        if url:
            # zoom=3 returns a much larger render than the default zoom=1
            url = url.replace("&zoom=1", "&zoom=3").replace("http://", "https://")
            out.append(("googlebooks", url, "Google Books volume %s" % it.get("id", "")))
    return out


def _font(px):
    """Baloo 2 if the system has it, else the closest rounded-bold available.

    The app's own Baloo 2 ships as woff2, which Pillow cannot read, so a generated
    cover falls back to a system face. It stays on-palette either way.
    """
    from PIL import ImageFont
    for name in ("Baloo2-Bold.ttf", "BalooBhai2-Bold.ttf", "arialbd.ttf",
                 "seguisb.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, px)
        except Exception:
            continue
    return ImageFont.load_default()


def generated(title, author):
    """A designed cover in Lunis's own language, for books with no usable art.

    Deliberately not an imitation book jacket: cream ground, navy frame, and the same
    line-spark-line ornament the reader draws under a chapter head, so a placeholder
    reads as part of the app rather than as a broken image.
    """
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (TARGET_W, TARGET_H), CREAM)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, TARGET_W, 22], fill=NAVY)                    # head band
    d.rectangle([0, TARGET_H - 12, TARGET_W, TARGET_H], fill=GOLD)  # foot rule
    # double frame: a navy keyline with a hairline inside it, like a printed board
    d.rectangle([40, 62, TARGET_W - 40, TARGET_H - 62], outline=NAVY, width=3)
    d.rectangle([50, 72, TARGET_W - 50, TARGET_H - 72], outline=(206, 196, 168), width=1)

    f_title, f_auth = _font(54), _font(27)
    max_w = TARGET_W - 160
    words, lines, cur = title.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if d.textlength(trial, font=f_title) > max_w and cur:
            lines.append(cur); cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    line_h, orn_gap, auth_gap = 64, 34, 30
    # measure the whole title+ornament+author block, then centre it in the frame so
    # the type sits optically middle instead of drifting low
    block_h = len(lines) * line_h + orn_gap + auth_gap + 30
    y = 62 + ((TARGET_H - 124) - block_h) // 2
    for ln in lines:
        d.text(((TARGET_W - d.textlength(ln, font=f_title)) / 2, y), ln, font=f_title, fill=NAVY)
        y += line_h
    y += orn_gap
    cx = TARGET_W / 2                                   # line - spark - line ornament
    d.line([(cx - 78, y), (cx - 26, y)], fill=(206, 196, 168), width=2)
    d.line([(cx + 26, y), (cx + 78, y)], fill=(206, 196, 168), width=2)
    r = 5
    d.polygon([(cx, y - r * 1.6), (cx + r * .7, y - r * .5), (cx + r * 1.6, y),
               (cx + r * .7, y + r * .5), (cx, y + r * 1.6), (cx - r * .7, y + r * .5),
               (cx - r * 1.6, y), (cx - r * .7, y - r * .5)], fill=GOLD)
    y += auth_gap
    d.text(((TARGET_W - d.textlength(author, font=f_auth)) / 2, y), author,
           font=f_auth, fill=(90, 117, 147))
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def usable(jpeg_bytes):
    """Reject scans that are technically fine but useless as a cover.

    Some Commons scans of a period binding are a plain dark board with no visible
    lettering: White Fang came back a solid blue rectangle, The Jungle Book almost
    pure black, Oliver Twist a featureless brown. On a shelf these read as broken
    images, so a designed placeholder is strictly better.

    Detail, not darkness, is the test - Tom Sawyer's cover is genuinely dark
    (mean 25) but richly detailed (edge 24), and must survive.
    """
    from PIL import Image, ImageFilter, ImageStat
    g = Image.open(io.BytesIO(jpeg_bytes)).convert("L")
    std = ImageStat.Stat(g).stddev[0]
    mean = ImageStat.Stat(g).mean[0]
    edge = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
    if std < 15:                       # flat field: no lettering, no art
        return False, "featureless (std %.1f)" % std
    if mean < 30 and edge < 15:        # dark AND smooth: an unlit board
        return False, "too dark (mean %.1f, edge %.1f)" % (mean, edge)
    return True, ""


def normalize(data):
    """Center-crop to 2:3 and resize to the target, so the grid stays uniform."""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    img = img.convert("RGB")
    w, h = img.size
    if w < MIN_SOURCE_W:
        return None, (w, h)
    want = TARGET_W / TARGET_H
    have = w / h
    if have > want:                       # too wide - trim the sides
        nw = int(h * want)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    elif have < want:                     # too tall - trim from the bottom, where
        nh = int(w / want)                # cover art least often carries the title
        img = img.crop((0, 0, w, nh))
    src = img.size
    img = img.resize((TARGET_W, TARGET_H), Image.LANCZOS)
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue(), src


def main(argv):
    write = "--write" in argv
    only = None
    if "--only" in argv:
        only = set(argv[argv.index("--only") + 1].split(","))
    raw = json.load(open(TABLE, encoding="utf-8"))
    table = {k: v for k, v in raw["titles"].items() if isinstance(v, dict)}
    # books where the only art Commons has is real but unusable as a cover (a
    # bookplate, or a photo of the bound book with its spine in frame) - no automatic
    # check catches those, so they are named by hand
    forced = set(x for x in raw.get("cover_force_generated", []) if not x.startswith("_"))
    ids = [b for b in sorted(table) if b.startswith("gb") and (not only or b in only)]
    print("re-sourcing %d covers -> %dx%d\n" % (len(ids), TARGET_W, TARGET_H))
    stats = {}
    for bid in ids:
        en_fp = os.path.join(BOOKS, bid, "en.json")
        if not os.path.exists(en_fp):
            print("%-8s no en.json, skipped" % bid); continue
        meta = json.load(open(en_fp, encoding="utf-8-sig"))
        title, author = meta.get("title", ""), meta.get("author", "")
        print("%-8s %s - %s" % (bid, title, author))
        # gather candidates from every source, then keep the highest-resolution one
        # rather than the first that happens to load - edition scans vary too much
        out = src_name = note = None
        best = None
        cands = []
        if bid in forced:
            print("      forced to generated cover (unusable source art)")
            cands = []
        for fn in ((wikimedia, open_library, google_books) if bid not in forced else ()):
            cands.extend(fn(title, author) or [])
            time.sleep(1.0)
        for cand_src, url, cand_note in cands[:6]:
            try:
                raw = get(url)
                norm, srcsize = normalize(raw)
            except Exception as e:
                # a 429 means we are going too fast, not that the image is bad -
                # back off once and give the same candidate a second chance
                if "429" in str(e):
                    time.sleep(4)
                    try:
                        raw = get(url); norm, srcsize = normalize(raw)
                    except Exception as e2:
                        print("      %s fetch failed: %s" % (cand_src, e2)); continue
                else:
                    print("      %s fetch failed: %s" % (cand_src, e)); continue
            if not norm:
                continue                      # under MIN_SOURCE_W, would be an upscale
            # Resolution alone picks badly: a scan of the whole bound book (spine on
            # the left, front cover to the right) is huge but far wider than 2:3, and
            # centre-cropping it keeps the spine and slices the title off the fore-edge.
            # Prefer a source already shaped like a cover, and only fall back to a
            # wide scan when nothing portrait-shaped exists.
            ok, why = usable(norm)
            if not ok:
                print("      %s rejected: %s" % (cand_src, why)); continue
            ratio = srcsize[0] / srcsize[1]
            portrait = PORTRAIT_LO <= ratio <= PORTRAIT_HI
            rank = (1 if portrait else 0, srcsize[0])
            if not best or rank > best[0]:
                best = (rank, srcsize[0], srcsize[1], norm, cand_src, cand_note, portrait)
        if best:
            out, src_name, note = best[3], best[4], best[5]
            print("      %s %dx%d%s -> %dx%d" % (src_name, best[1], best[2],
                  "" if best[6] else " (wide scan, cropped)", TARGET_W, TARGET_H))
        if not out:
            out, src_name, note = generated(title, author), "generated", "Lunis generated cover"
            print("      generated placeholder")
        stats[src_name] = stats.get(src_name, 0) + 1
        if write:
            with open(os.path.join(BOOKS, bid, "cover.jpg"), "wb") as f:
                f.write(out)
            # record where it came from: the app reads books/<id>/cover.jpg once, and
            # this keeps the provenance auditable without re-querying anything
            with open(os.path.join(BOOKS, bid, "cover.json"), "w", encoding="utf-8") as f:
                json.dump({"source": src_name, "note": note,
                           "width": TARGET_W, "height": TARGET_H}, f, ensure_ascii=False, indent=1)
        time.sleep(1.2)                     # be polite to the APIs
    print("\n%s: %s" % ("WROTE" if write else "DRY RUN",
                        ", ".join("%s=%d" % kv for kv in sorted(stats.items()))))


if __name__ == "__main__":
    main(sys.argv[1:])
