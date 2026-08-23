"""Hardware tiering tests.

The probes themselves depend on the machine running the tests, so what is pinned here
is the classification rule and the serving policy it produces - the parts that decide
whether a donated laptop over-commits itself.
"""

import unittest

from tutor_core import hardware
from tutor_core.hardware import (TIER_MID, TIER_STRONG, TIER_WEAK, HardwareConfig,
                                 _tier_for, benchmark, detect)


class TestTierRules(unittest.TestCase):

    def test_weak_disqualifiers(self):
        self.assertEqual(_tier_for(2, 4.0, True), TIER_WEAK)     # 2012 dual core
        self.assertEqual(_tier_for(2, 16.0, True), TIER_WEAK)    # cores dominate
        self.assertEqual(_tier_for(8, 4.0, True), TIER_WEAK)     # RAM dominates
        self.assertEqual(_tier_for(8, 32.0, False), TIER_WEAK)   # no AVX2 dominates

    def test_mid(self):
        self.assertEqual(_tier_for(4, 8.0, True), TIER_MID)
        self.assertEqual(_tier_for(6, 6.0, True), TIER_MID)

    def test_strong(self):
        self.assertEqual(_tier_for(4, 12.0, True), TIER_STRONG)
        self.assertEqual(_tier_for(8, 32.0, True), TIER_STRONG)

    def test_the_gap_between_tiers_falls_to_the_conservative_side(self):
        """A 3-core 8GB machine matches neither the mid nor the strong description.
        It must land in Tier 2, never be promoted."""
        self.assertEqual(_tier_for(3, 8.0, True), TIER_MID)
        self.assertEqual(_tier_for(3, 16.0, True), TIER_MID)


class TestPolicy(unittest.TestCase):

    def test_slots_per_tier(self):
        self.assertEqual(HardwareConfig(TIER_WEAK, 2, 4, 4.0, False).max_parallel_slots, 1)
        self.assertEqual(HardwareConfig(TIER_MID, 4, 8, 8.0, True).max_parallel_slots, 3)
        self.assertEqual(HardwareConfig(TIER_STRONG, 8, 16, 16.0, True).max_parallel_slots, 5)

    def test_llama_args_size_the_context_for_all_slots(self):
        cfg = HardwareConfig(TIER_MID, 4, 8, 8.0, True)
        args = cfg.llama_server_args("/models/m.gguf")
        self.assertIn("--cont-batching", args)
        self.assertEqual(args[args.index("--parallel") + 1], "3")
        # llama-server splits --ctx-size across slots, so the total must cover them all
        self.assertEqual(args[args.index("--ctx-size") + 1], str(2048 * 3))
        self.assertEqual(args[args.index("--threads") + 1], "4")

    def test_detect_returns_a_usable_config_on_this_machine(self):
        cfg = detect(model="test.gguf")
        self.assertIn(cfg.tier, (TIER_WEAK, TIER_MID, TIER_STRONG))
        self.assertGreaterEqual(cfg.physical_cores, 1)
        self.assertGreaterEqual(cfg.max_parallel_slots, 1)
        self.assertEqual(cfg.as_dict()["model"], "test.gguf")


class TestBenchmark(unittest.TestCase):

    def test_unreachable_server_warns_but_never_fails_startup(self):
        cfg = HardwareConfig(TIER_MID, 4, 8, 8.0, True)
        out = benchmark(cfg, "http://127.0.0.1:1/v1/chat/completions", "m", timeout=0.5)
        self.assertIs(out, cfg)
        self.assertIsNone(cfg.tokens_per_sec)
        self.assertTrue(any("benchmark failed" in w for w in cfg.warnings))

    def test_slow_box_is_flagged_against_its_spec_tier(self):
        """A machine whose specs say Tier 3 but that measures 2 tok/s is thermally
        throttled or swapping - the whole reason the benchmark exists."""
        cfg = HardwareConfig(TIER_STRONG, 8, 16, 16.0, True)
        served = {"usage": {"completion_tokens": 20}}

        import json
        import io
        import urllib.request

        class _Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=None):
            import time
            time.sleep(0.2)                      # 20 tokens / 0.2s = 100 tok/s
            return _Resp(json.dumps(served).encode())

        real = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        try:
            benchmark(cfg, "http://x/v1/chat/completions", "m")
            self.assertGreater(cfg.tokens_per_sec, 7.0)
            self.assertEqual(cfg.warnings, [])

            slow = HardwareConfig(TIER_STRONG, 8, 16, 16.0, True)
            served["usage"]["completion_tokens"] = 1   # 1 token / 0.2s = 5 tok/s
            benchmark(slow, "http://x/v1/chat/completions", "m")
            self.assertTrue(any("slower than its specs" in w for w in slow.warnings))
        finally:
            urllib.request.urlopen = real


if __name__ == "__main__":
    unittest.main()
