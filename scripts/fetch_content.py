#!/usr/bin/env python3
"""Download the video lessons into content/.

The 127 lesson videos are not stored in the git repository. They are published
as a release asset and downloaded by this script. server/install.sh runs it for
you, so most people never need to call it directly.

Run it yourself if you skipped the download during install, if it failed, or if
you are moving the videos onto a machine that has no internet.

    python3 scripts/fetch_content.py              # show what you have
    python3 scripts/fetch_content.py --download   # download the videos

The videos are Khan Academy material under CC BY-NC-SA 4.0, which is not the
same licence as the Lunis code. See NOTICE.md.
"""
import argparse
import json
import os
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CONTENT = os.path.join(REPO, "content")
CATALOG = os.path.join(REPO, "data", "catalog.json")

# The newest release of this repository, whatever its version number.
# Override with LUNIS_CONTENT_URL to install from a local web server, a
# mirror, or a file:// path on a USB stick.
DEFAULT_BUNDLE_URL = ("https://github.com/lunislearning/Lunis"
                      "/releases/latest/download/lunis-content.tar.gz")
BUNDLE_URL = os.environ.get("LUNIS_CONTENT_URL", "").strip() or DEFAULT_BUNDLE_URL


def load_catalog():
    # utf-8-sig: the catalog carries a byte order mark.
    with open(CATALOG, encoding="utf-8-sig") as fh:
        return json.load(fh)


def survey(entries):
    have, missing = [], []
    for e in entries:
        vid = e.get("id")
        if not vid:
            continue
        target = have if os.path.exists(os.path.join(CONTENT, vid + ".mp4")) else missing
        target.append(e)
    return have, missing


def report(have, missing):
    total = len(have) + len(missing)
    print("Video lessons: %d of %d present." % (len(have), total))
    if not missing:
        print("Nothing left to download.")
        return
    print()
    print("To download them:")
    print("    python3 scripts/fetch_content.py --download")
    print()
    print("On a machine with no internet, copy the content folder from a")
    print("machine that has them, or point this at a local copy:")
    print("    LUNIS_CONTENT_URL=file:///media/usb/lunis-content.tar.gz \\")
    print("        python3 scripts/fetch_content.py --download")
    print()
    print("Everything except the video lessons works without them. The Reading")
    print("Hub, the Homework Helper, quizzes and the teacher dashboard are all")
    print("unaffected.")


def _safe_members(tf):
    """Yield members, refusing anything that would write outside content/.

    The archive comes from a URL, and a URL is not allowed to decide where
    files land on disk.
    """
    for m in tf.getmembers():
        name = os.path.normpath(m.name)
        if name.startswith(("/", "\\")) or name.split(os.sep)[0] == "..":
            raise ValueError("refusing unsafe path in archive: %r" % m.name)
        if m.issym() or m.islnk():
            raise ValueError("refusing link in archive: %r" % m.name)
        yield m


def download(url):
    os.makedirs(CONTENT, exist_ok=True)
    print("Downloading video lessons from:")
    print("    %s" % url)
    print("About 570 MB. This is the slow part of the install.")
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp.close()
    try:
        try:
            resp = urllib.request.urlopen(url, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print()
                print("The download returned 404, so no video bundle has been")
                print("published for this version yet.")
                print()
                print("Lunis still installs and runs. Only the video lessons")
                print("are missing. Retry later with:")
                print("    python3 scripts/fetch_content.py --download")
                return 1
            print("Download failed: HTTP %s %s" % (e.code, e.reason))
            return 1
        except Exception as e:
            print("Download failed: %s" % e)
            return 1

        with resp, open(tmp.name, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                if total:
                    sys.stdout.write("\r    %d%% (%d MB of %d MB)"
                                     % (done * 100 // total, done >> 20, total >> 20))
                else:
                    sys.stdout.write("\r    %d MB" % (done >> 20))
                sys.stdout.flush()
        print()
        print("Unpacking into content/")
        with tarfile.open(tmp.name) as tf:
            tf.extractall(CONTENT, members=_safe_members(tf))
        print("Done.")
        return 0
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser(
        description="Download the Lunis video lessons into content/.")
    ap.add_argument("--download", action="store_true",
                    help="download and unpack the video lessons")
    args = ap.parse_args()

    if not os.path.exists(CATALOG):
        print("Cannot find data/catalog.json. Run this from inside the Lunis folder.")
        return 2

    entries = load_catalog()

    if args.download:
        have, missing = survey(entries)
        if not missing:
            print("All %d video lessons are already present." % len(have))
            return 0
        if download(BUNDLE_URL):
            return 1

    have, missing = survey(entries)
    report(have, missing)

    if not missing:
        print()
        print("Next, build the text the tutor reads from the captions:")
        print("    python3 app/prep.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
