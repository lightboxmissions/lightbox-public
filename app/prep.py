#!/usr/bin/env python3
"""One-time prep: turn each .srt into a clean plain-text transcript at
~/lightbox/transcripts/<friendlyID>.txt, using the catalog to map IDs to files."""
import json, os, re

BASE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(BASE) == "app":
    BASE = os.path.dirname(BASE)
CONTENT = os.path.join(BASE, "content")
TRANS = os.path.join(BASE, "transcripts")
os.makedirs(TRANS, exist_ok=True)

with open(os.path.join(BASE, "data", "catalog.json"), encoding="utf-8-sig") as f:
    catalog = json.load(f)

def srt_to_text(path):
    with open(path, encoding="utf-8", errors="ignore") as f:
        raw = f.read()
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.isdigit():
            continue
        if "-->" in ln:
            continue
        ln = re.sub(r"<[^>]+>", "", ln)          # strip tags
        lines.append(ln)
    # collapse consecutive duplicate lines (srt often repeats rolling captions)
    out = []
    for ln in lines:
        if not out or out[-1] != ln:
            out.append(ln)
    text = " ".join(out)
    text = re.sub(r"\s+", " ", text).strip()
    return text

ok = miss = 0
for e in catalog:
    src = os.path.join(CONTENT, e["id"] + ".srt")
    if not os.path.exists(src):
        print("MISSING:", e["id"], src)
        miss += 1
        continue
    txt = srt_to_text(src)
    with open(os.path.join(TRANS, e["id"] + ".txt"), "w", encoding="utf-8") as f:
        f.write(txt)
    ok += 1
print("transcripts written: %d   missing: %d" % (ok, miss))
