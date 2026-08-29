"""HTTP layer (Phase 5) - single student endpoint plus a health endpoint.

Standard-library http.server, matching the rest of the Lunis stack. The donated
laptops are set up offline and have no pip, so a framework would be one more thing to
fail during a deployment in a school with no internet.

Two ways to use this:

  * standalone, for testing a laptop before it ships:
        python -m tutor_core.service --model-path ~/models/model.gguf
  * embedded, from the existing server.py:
        from tutor_core.service import build_tutor
        TUTOR = build_tutor(Config(llama_url=LLAMA, model=MODEL))
        answer = TUTOR.ask(question)

The model is reached over the local llama-server HTTP API, which must already be
running as a persistent background process - never relaunched per request.
"""

import argparse
import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import hardware
from .logging_ import TutorLog
from .pipeline import Tutor
from .queueing import QueueTimeout

__all__ = ["Config", "build_tutor", "TutorHandler", "serve"]

DEFAULT_MODEL = "qwen2.5-3b-instruct-q4_k_m.gguf"

# Which model ships is a Phase 6 measurement, not an assumption. Phi-4-mini has the
# stronger small-model math benchmarks; Qwen2.5-3B is smaller and faster per token on
# the same CPU. Swapping between them is this one config value - run bench/run_batch.py
# against each and compare before changing it.


class Config(object):
    __slots__ = ("llama_url", "model", "model_path", "log_path", "timeout",
                 "queue_timeout", "benchmark", "use_templates", "force_tier")

    def __init__(self, llama_url="http://127.0.0.1:8080/v1/chat/completions",
                 model=DEFAULT_MODEL, model_path="", log_path="data/tutor_log.jsonl",
                 timeout=180.0, queue_timeout=300.0, benchmark=True,
                 use_templates=True, force_tier=0):
        self.llama_url = llama_url
        self.model = model
        self.model_path = model_path
        self.log_path = log_path
        self.timeout = timeout
        self.queue_timeout = queue_timeout
        self.benchmark = benchmark
        self.use_templates = use_templates
        self.force_tier = force_tier      # 0 = detect; 1-3 pins the tier by hand


def make_llm(config):
    """A plain `llm(messages, max_tokens) -> text` callable over llama-server."""

    def llm(messages, max_tokens):
        body = json.dumps({"model": config.model, "messages": messages,
                           "max_tokens": max_tokens, "temperature": 0.3,
                           "stream": False}).encode("utf-8")
        req = urllib.request.Request(config.llama_url, data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=config.timeout) as r:
            out = json.loads(r.read().decode("utf-8"))
        return out["choices"][0]["message"]["content"]

    return llm


def build_tutor(config):
    """Detect the host, benchmark it, and wire up a Tutor. Run once at startup."""
    hw = hardware.detect(model=config.model)
    if config.force_tier:
        hw = hardware.HardwareConfig(config.force_tier, hw.physical_cores,
                                     hw.logical_cores, hw.ram_gb, hw.avx2, config.model)
        hw.warnings.append("tier pinned to %d by configuration" % config.force_tier)
    if config.benchmark:
        hardware.benchmark(hw, config.llama_url, config.model)
    log = TutorLog(config.log_path, hw)
    for w in hw.warnings:
        log.warning(w)
    return Tutor(make_llm(config), hw, log=log, use_templates=config.use_templates)


class TutorHandler(BaseHTTPRequestHandler):
    """Single question endpoint plus health. `tutor` is set on the server object."""

    server_version = "LunisTutor/1.0"

    def _send(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass                            # the tutor log is the record, not stderr noise

    def do_GET(self):
        if self.path.split("?")[0] == "/api/health":
            self._send(200, self.server.tutor.health())
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path.split("?")[0] != "/api/tutor":
            self._send(404, {"error": "not found"})
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"error": "expected JSON with a 'question' field"})
            return
        question = (payload.get("question") or "").strip()
        if not question:
            self._send(400, {"error": "expected JSON with a 'question' field"})
            return

        tutor = self.server.tutor
        waited_at = {}

        def on_wait(position):
            # The client cannot be told mid-request on a plain POST, so the position is
            # recorded and returned with the answer, and the health endpoint carries
            # live depth for a UI that polls. An honest wait beats a silent hang.
            waited_at["position"] = position

        try:
            answer = tutor.ask(question, on_wait=on_wait,
                               timeout=self.server.queue_timeout)
        except QueueTimeout as e:
            self._send(503, {"error": "the tutor is busy", "detail": str(e),
                             "queue": tutor.queue.stats()})
            return
        out = answer.as_dict()
        out["queue_position"] = waited_at.get("position", 0)
        self._send(200, out)


def serve(config, host="127.0.0.1", port=8091):
    tutor = build_tutor(config)
    httpd = ThreadingHTTPServer((host, port), TutorHandler)
    httpd.tutor = tutor
    httpd.queue_timeout = config.queue_timeout
    print("tier %d (%s), %d slot(s), ctx %d, model %s"
          % (tutor.hardware.tier, hardware.TIER_NAMES[tutor.hardware.tier],
             tutor.hardware.max_parallel_slots, tutor.hardware.ctx_size, config.model))
    if tutor.hardware.tokens_per_sec:
        print("measured %.2f tok/s" % tutor.hardware.tokens_per_sec)
    for w in tutor.hardware.warnings:
        print("warning: %s" % w)
    if tutor.hardware.model and config.model_path:
        print("llama-server args for this tier: %s"
              % " ".join(tutor.hardware.llama_server_args(config.model_path)))
    print("listening on http://%s:%d/api/tutor" % (host, port))
    httpd.serve_forever()


def main(argv=None):
    p = argparse.ArgumentParser(description="Lunis offline math tutor")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8091)
    p.add_argument("--llama-url", default="http://127.0.0.1:8080/v1/chat/completions")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--model-path", default="", help="only used to print llama-server args")
    p.add_argument("--log", default="data/tutor_log.jsonl")
    p.add_argument("--force-tier", type=int, default=0, choices=[0, 1, 2, 3])
    p.add_argument("--no-benchmark", action="store_true")
    p.add_argument("--no-templates", action="store_true",
                   help="send every computational question to the model (for testing)")
    p.add_argument("--print-llama-args", action="store_true",
                   help="print this tier's llama-server flags and exit, for install "
                        "scripts and systemd units to use when starting the model")
    a = p.parse_args(argv)
    if a.print_llama_args:
        hw = hardware.detect(model=a.model)
        if a.force_tier:
            hw = hardware.HardwareConfig(a.force_tier, hw.physical_cores,
                                         hw.logical_cores, hw.ram_gb, hw.avx2, a.model)
        print(" ".join(hw.llama_server_args(a.model_path or "MODEL_PATH")))
        return 0
    serve(Config(llama_url=a.llama_url, model=a.model, model_path=a.model_path,
                 log_path=a.log, benchmark=not a.no_benchmark,
                 use_templates=not a.no_templates, force_tier=a.force_tier),
          a.host, a.port)


if __name__ == "__main__":
    main()
