#!/usr/bin/env python3
"""
build_content.py - populate the repo's content/ folder so the app can play videos.

The app serves videos as flat files named by lesson code:  content/<CODE>.mp4
and captions as  content/<CODE>.srt  (e.g. content/CO1.mp4, content/CO1.srt).

The original Khan Academy downloads are stored per-topic with long human names
like:  01_Counting/Comparing numbers of objects | ... [ytid].mp4
This script reads data/catalog.json (which maps each CODE to its topic folder +
original filename) and copies each video/caption into content/ under its code.

Usage:
    python tools/build_content.py <path-to-video-archive>

<path-to-video-archive> is the folder that contains the 01_Counting, 02_Place_Value,
... topic folders. If you omit it, it defaults to the parent of this repo.

Nothing is deleted; existing files in content/ are skipped unless --force is given.
"""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONTENT = os.path.join(REPO, "content")
CATALOG = os.path.join(REPO, "data", "catalog.json")

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv
    archive = args[0] if args else os.path.dirname(REPO)
    archive = os.path.abspath(archive)

    if not os.path.isdir(archive):
        sys.exit("Archive folder not found: %s" % archive)
    with open(CATALOG, encoding="utf-8-sig") as f:
        catalog = json.load(f)
    os.makedirs(CONTENT, exist_ok=True)

    copied = skipped = missing = 0
    for e in catalog:
        code = e["id"]
        for ext, key in ((".mp4", "video"), (".srt", "transcript")):
            src = os.path.join(archive, e["topic"], e[key])
            dst = os.path.join(CONTENT, code + ext)
            if os.path.exists(dst) and not force:
                skipped += 1
                continue
            if not os.path.exists(src):
                print("MISSING:", code, "->", src)
                missing += 1
                continue
            shutil.copy2(src, dst)
            copied += 1
    print("\ncopied: %d   skipped(existing): %d   missing: %d" % (copied, skipped, missing))
    print("content/ is at:", CONTENT)
    print("\nNext, build the plain-text transcripts the AI reads:")
    print("    python app/prep.py")

if __name__ == "__main__":
    main()
