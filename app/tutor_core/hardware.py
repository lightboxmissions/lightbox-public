"""Hardware detection and tiering (Phase 1).

Donated laptops range from 2012-era 4GB dual-cores to modern 16GB machines. The tier
decides how many students the box serves at once and how big a context window it can
afford - nothing else in the system needs to know what CPU it is running on.

Tier 1 is NOT "the tier that avoids the model". Conceptual questions require real
inference on every tier; Tier 1's job is to run the model conservatively (one slot,
small context) and let the queue absorb the rest.

Pure standard library - psutil would need pip, and these boxes are set up offline.

Isolated and swappable: everything outside this module consumes the HardwareConfig
object, never the raw probes.
"""

import ctypes
import json
import os
import platform
import re
import time
import urllib.request

__all__ = ["HardwareConfig", "detect", "benchmark", "TIER_WEAK", "TIER_MID", "TIER_STRONG"]

TIER_WEAK = 1
TIER_MID = 2
TIER_STRONG = 3

# Per-tier serving policy. Context sizes are per-slot, so total KV cache is roughly
# ctx_size * max_parallel_slots - the reason Tier 1 gets both fewer slots and a
# smaller window rather than just fewer slots.
TIER_POLICY = {
    TIER_WEAK:   {"max_parallel_slots": 1, "ctx_size": 1024, "min_tokens_per_sec": 1.5},
    TIER_MID:    {"max_parallel_slots": 3, "ctx_size": 2048, "min_tokens_per_sec": 4.0},
    TIER_STRONG: {"max_parallel_slots": 5, "ctx_size": 4096, "min_tokens_per_sec": 7.0},
}

TIER_NAMES = {TIER_WEAK: "weak", TIER_MID: "mid", TIER_STRONG: "strong"}


class HardwareConfig(object):
    """What the rest of the system consumes. Everything else here is a probe."""

    __slots__ = ("tier", "physical_cores", "logical_cores", "ram_gb", "avx2",
                 "max_parallel_slots", "ctx_size", "tokens_per_sec", "warnings", "model")

    def __init__(self, tier, physical_cores, logical_cores, ram_gb, avx2, model=""):
        self.tier = tier
        self.physical_cores = physical_cores
        self.logical_cores = logical_cores
        self.ram_gb = ram_gb
        self.avx2 = avx2
        self.model = model
        policy = TIER_POLICY[tier]
        self.max_parallel_slots = policy["max_parallel_slots"]
        self.ctx_size = policy["ctx_size"]
        self.tokens_per_sec = None          # filled in by benchmark()
        self.warnings = []

    def as_dict(self):
        return {"tier": self.tier, "tier_name": TIER_NAMES[self.tier],
                "physical_cores": self.physical_cores,
                "logical_cores": self.logical_cores,
                "ram_gb": round(self.ram_gb, 1), "avx2": self.avx2,
                "max_parallel_slots": self.max_parallel_slots,
                "ctx_size": self.ctx_size, "tokens_per_sec": self.tokens_per_sec,
                "model": self.model, "warnings": list(self.warnings)}

    def llama_server_args(self, model_path):
        """The llama-server flags this tier implies. Kept here so the tier policy has
        exactly one home."""
        return ["--model", model_path,
                "--parallel", str(self.max_parallel_slots),
                "--ctx-size", str(self.ctx_size * self.max_parallel_slots),
                "--threads", str(max(1, self.physical_cores)),
                "--cont-batching"]

    def __repr__(self):
        return "HardwareConfig(tier=%d %s, cores=%d/%d, ram=%.1fGB, avx2=%s, slots=%d)" % (
            self.tier, TIER_NAMES[self.tier], self.physical_cores, self.logical_cores,
            self.ram_gb, self.avx2, self.max_parallel_slots)


# ---------- probes ----------

def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def physical_cores():
    """Physical cores, not hyperthreads. Two hyperthreads on one 2012 core do not make
    a machine able to serve two students."""
    cpuinfo = _read("/proc/cpuinfo")
    if cpuinfo:
        seen = set()
        phys_id = core_id = None
        for line in cpuinfo.splitlines():
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k == "physical id":
                phys_id = v
            elif k == "core id":
                core_id = v
                seen.add((phys_id, core_id))
            elif not line.strip():
                phys_id = core_id = None
        if seen:
            return len(seen)
        n = re.findall(r"^cpu cores\s*:\s*(\d+)", cpuinfo, re.M)
        if n:
            return int(n[0])
    if platform.system() == "Windows":
        try:
            with os.popen("wmic cpu get NumberOfCores") as p:
                out = p.read()
            nums = [int(x) for x in re.findall(r"\d+", out)]
            if nums:
                return sum(nums)
        except OSError:
            pass
    # No physical-core information available: halve the logical count rather than
    # trusting it, so an unknown machine lands in a lower tier instead of a higher one.
    logical = os.cpu_count() or 1
    return max(1, logical // 2)


def ram_gb():
    meminfo = _read("/proc/meminfo")
    m = re.search(r"^MemTotal:\s*(\d+)\s*kB", meminfo, re.M)
    if m:
        return int(m.group(1)) / (1024.0 * 1024.0)
    if platform.system() == "Windows":
        class _MemStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = _MemStatus()
        st.dwLength = ctypes.sizeof(_MemStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return st.ullTotalPhys / float(1024 ** 3)
    try:
        return (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / float(1024 ** 3)
    except (ValueError, OSError, AttributeError):
        return 0.0


def has_avx2():
    cpuinfo = _read("/proc/cpuinfo")
    if cpuinfo:
        return bool(re.search(r"^flags\s*:.*\bavx2\b", cpuinfo, re.M))
    if platform.system() == "Windows":
        # PF_AVX2_INSTRUCTIONS_AVAILABLE = 40
        try:
            return bool(ctypes.windll.kernel32.IsProcessorFeaturePresent(40))
        except (AttributeError, OSError):
            return False
    return False


def _tier_for(cores, ram, avx2):
    """Tier rules, in priority order.

    The spec's three tiers leave a gap (a 3-core, 8GB machine matches neither the mid
    nor the strong description), so anything that is not disqualified into Tier 1 and
    not clearly Tier 3 lands in Tier 2. That is the safe direction: Tier 2 is the
    conservative middle, not an upgrade.
    """
    if cores <= 2 or ram < 6.0 or not avx2:
        return TIER_WEAK
    if cores >= 4 and ram >= 12.0:
        return TIER_STRONG
    return TIER_MID


def detect(model=""):
    """Classify the host. Cheap - a few file reads, run once at startup."""
    cores = physical_cores()
    logical = os.cpu_count() or cores
    ram = ram_gb()
    avx2 = has_avx2()
    cfg = HardwareConfig(_tier_for(cores, ram, avx2), cores, logical, ram, avx2, model)
    if ram == 0.0:
        cfg.warnings.append("could not read total RAM; assumed the weakest tier rules")
    return cfg


# ---------- startup micro-benchmark ----------

BENCH_PROMPT = "Explain in two short sentences why 2 plus 3 equals 5."


def benchmark(config, llama_url, model, timeout=60.0, max_tokens=48):
    """Measure real tokens/sec against llama-server and sanity-check the tier.

    Specs on paper lie: thermal throttling, a background updater, or a swap-thrashing
    4GB box all look fine to the probes above. This is the only check that sees what
    the machine actually does. Roughly 5 seconds on a healthy box.

    Mutates and returns `config`. A failure here is never fatal - an unmeasurable box
    keeps its spec-based tier and gets a warning.
    """
    body = json.dumps({"model": model,
                       "messages": [{"role": "user", "content": BENCH_PROMPT}],
                       "max_tokens": max_tokens, "temperature": 0.0,
                       "stream": False}).encode("utf-8")
    req = urllib.request.Request(llama_url, data=body,
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
    except Exception as e:                        # noqa: BLE001 - never fail startup
        config.warnings.append("startup benchmark failed (%s: %s); "
                               "tier left at spec-based value"
                               % (type(e).__name__, e))
        return config
    elapsed = max(time.time() - start, 1e-6)
    tokens = (out.get("usage") or {}).get("completion_tokens")
    if not tokens:
        tokens = len((out["choices"][0]["message"]["content"] or "").split())
    config.tokens_per_sec = round(tokens / elapsed, 2)

    expected = TIER_POLICY[config.tier]["min_tokens_per_sec"]
    if config.tokens_per_sec < expected:
        config.warnings.append(
            "measured %.2f tok/s but tier %d (%s) expects at least %.1f - this box is "
            "slower than its specs suggest; consider forcing a lower tier"
            % (config.tokens_per_sec, config.tier, TIER_NAMES[config.tier], expected))
    return config
