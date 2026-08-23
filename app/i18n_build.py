#!/usr/bin/env python3
"""Pre-build translated captions (.vtt) for every video in every non-English
language, so subtitles appear instantly. Safe to re-run (skips cached files).
Run niced in the background:  nice -n 19 python3 i18n_build.py
"""
import sys, time, threading, queue
import server as S

LANGS = [l for l in S.LANGS if l != "en"]
ids = [e["id"] for e in S.CATALOG]
work = queue.Queue()
for lang in LANGS:
    for vid in ids:
        work.put((vid, lang))
TOTAL = work.qsize()
done = [0]
lock = threading.Lock()

def worker():
    while True:
        try:
            vid, lang = work.get_nowait()
        except queue.Empty:
            return
        try:
            S.make_vtt(vid, lang)
        except Exception as e:
            print("FAIL %s/%s: %s" % (vid, lang, e), flush=True)
        with lock:
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == TOTAL:
                print("captions %d/%d" % (done[0], TOTAL), flush=True)

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    print("Building %d captions (%s) with %d workers" % (TOTAL, ",".join(LANGS), n), flush=True)
    t0 = time.time()
    ts = [threading.Thread(target=worker, daemon=True) for _ in range(n)]
    for th in ts:
        th.start()
    for th in ts:
        th.join()
    print("ALL CAPTIONS DONE: %d in %ds" % (TOTAL, int(time.time() - t0)), flush=True)
