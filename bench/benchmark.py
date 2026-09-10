#!/usr/bin/env python3
"""Sequential warm-path benchmark for a FLUX serverless endpoint.

Sends one request at a time, waiting for each to finish before sending the
next, so later runs reuse an already-warm worker. Concurrent requests make
RunPod scale up a separate worker per job, and every one of those pays the
full cold cost -- which is why a concurrent test cannot measure the warm path.

Runs are classified by the worker that served them: the first job seen on a
given worker is COLD (container start plus ~17 GB of weights into VRAM), and
any later job on that same worker is WARM. That classification comes from the
data rather than from assuming run 1 is the only cold one.

Usage:

    export RUNPOD_API_KEY=...            # never committed; keep it in env
    python bench/benchmark.py --endpoint <ENDPOINT_ID> --label dev
    python bench/benchmark.py --endpoint <ENDPOINT_ID> --label schnell

Both endpoints get the same prompts and the same seeds, so timings and images
are directly comparable. Images and a results JSON are written under --out.

Standard library only -- no pip install needed.
"""

import argparse
import base64
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.request

# Fixed prompt/seed pairs, shared by every run of every variant so the
# comparison is like-for-like. The first is the client's actual use case.
PROMPTS = [
    ("25-year-old woman, green eyes, dark brown hair, soft smile, cozy bedroom, natural light", 1111),
    ("a handsome boy, cyberpunk style, hood, neon lights, high-tech clothing", 2222),
    ("a red fox in deep snow, golden hour, shallow depth of field", 3333),
    ("architectural photograph of a brutalist concrete library, overcast sky", 4444),
    ("still life, ceramic bowl of lemons on rough linen, soft studio lighting", 5555),
]


def api(url, key, payload=None, timeout=60):
    """POST when payload is given, else GET. Returns parsed JSON."""
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    req.add_header("Authorization", "Bearer " + key)
    if data:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def run_one(base, key, prompt, seed, steps, interval, timeout):
    """Submit one job and poll until it settles. Returns a result dict."""
    body = {"input": {"prompt": prompt, "seed": seed}}
    if steps is not None:
        body["input"]["steps"] = steps

    started = time.monotonic()
    submitted = api(base + "/run", key, body)
    job_id = submitted.get("id")
    if not job_id:
        return {"ok": False, "error": "no job id returned: %s" % submitted}

    deadline = started + timeout
    while time.monotonic() < deadline:
        job = api("%s/status/%s" % (base, job_id), key)
        status = job.get("status")

        if status == "COMPLETED":
            wall = time.monotonic() - started
            images = (job.get("output") or {}).get("images") or []
            return {
                "ok": True,
                "id": job_id,
                "status": status,
                "worker": job.get("workerId"),
                "delay_s": (job.get("delayTime") or 0) / 1000.0,
                "exec_s": (job.get("executionTime") or 0) / 1000.0,
                "wall_s": wall,
                "images": images,
                "seed_used": (job.get("output") or {}).get("seed"),
            }

        if status not in ("IN_QUEUE", "IN_PROGRESS"):
            return {
                "ok": False,
                "id": job_id,
                "status": status,
                "worker": job.get("workerId"),
                "error": job.get("error") or "job %s" % status,
            }

        time.sleep(interval)

    return {"ok": False, "id": job_id, "error": "timed out after %ss" % timeout}


def summarize(rows):
    """Split completed runs into cold and warm by first-use of each worker."""
    seen, cold, warm = set(), [], []
    for r in rows:
        if not r.get("ok"):
            continue
        worker = r.get("worker")
        (warm if worker in seen else cold).append(r)
        seen.add(worker)
    return cold, warm


def stats(rows, field):
    vals = [r[field] for r in rows if field in r]
    if not vals:
        return None
    return {
        "n": len(vals),
        "min": min(vals),
        "mean": statistics.fmean(vals),
        "median": statistics.median(vals),
        "max": max(vals),
    }


def fmt(s):
    return "-" if s is None else "%6.2f  %6.2f  %6.2f  %6.2f" % (
        s["min"], s["mean"], s["median"], s["max"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--endpoint", required=True, help="RunPod endpoint ID")
    ap.add_argument("--label", default="run", help="name for this variant, e.g. dev / schnell")
    ap.add_argument("--runs", type=int, default=6, help="number of sequential requests (default 6)")
    ap.add_argument("--steps", type=int, default=None,
                    help="override steps; omit to use the workflow's own default")
    ap.add_argument("--out", default="bench/results", help="output directory")
    ap.add_argument("--interval", type=float, default=1.0, help="poll interval seconds")
    ap.add_argument("--timeout", type=float, default=600.0, help="per-job timeout seconds")
    args = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("RUNPOD_API_KEY is not set. Export it; do not pass it on the command line.")

    base = "https://api.runpod.ai/v2/" + args.endpoint
    outdir = pathlib.Path(args.out) / args.label
    outdir.mkdir(parents=True, exist_ok=True)

    print("endpoint : %s" % args.endpoint)
    print("label    : %s" % args.label)
    print("runs     : %d (sequential)" % args.runs)
    print("steps    : %s" % (args.steps if args.steps is not None else "workflow default"))
    print()
    print("  #  status      worker            delay    exec    wall")
    print("  " + "-" * 58)

    rows = []
    for i in range(args.runs):
        prompt, seed = PROMPTS[i % len(PROMPTS)]
        r = run_one(base, key, prompt, seed, args.steps, args.interval, args.timeout)
        r["run"] = i + 1
        r["prompt"] = prompt
        r["seed"] = seed

        if r.get("ok"):
            for n, img in enumerate(r.pop("images")):
                if img.get("type") != "base64":
                    print("     (image is %s, not base64 - not saved)" % img.get("type"))
                    continue
                name = "run%02d_seed%d%s.png" % (i + 1, seed, "" if n == 0 else "_%d" % n)
                (outdir / name).write_bytes(base64.b64decode(img["data"]))
            print("  %2d  %-10s  %-16s  %6.2f  %6.2f  %6.2f"
                  % (r["run"], "OK", (r.get("worker") or "?")[:16],
                     r["delay_s"], r["exec_s"], r["wall_s"]))
        else:
            print("  %2d  %-10s  %-16s  %s"
                  % (r["run"], r.get("status") or "ERROR",
                     (r.get("worker") or "?")[:16], str(r.get("error"))[:60]))
        rows.append(r)

    cold, warm = summarize(rows)
    failed = [r for r in rows if not r.get("ok")]

    print()
    print("=" * 62)
    print("SUMMARY - %s" % args.label)
    print("=" * 62)
    print("completed %d, failed %d   |   cold %d, warm %d"
          % (len(rows) - len(failed), len(failed), len(cold), len(warm)))
    print()
    print("                       min    mean  median     max   (seconds)")
    for name, group in (("COLD", cold), ("WARM", warm)):
        if not group:
            print("  %s  (none)" % name)
            continue
        print("  %s  n=%d" % (name, len(group)))
        for field, lbl in (("delay_s", "queue+boot"), ("exec_s", "execution"), ("wall_s", "wall clock")):
            print("    %-12s %s" % (lbl, fmt(stats(group, field))))
    if not warm:
        print()
        print("  No warm runs recorded - every job landed on a fresh worker.")
        print("  Raise the endpoint's idle timeout so a worker survives between")
        print("  requests, then run this again.")

    results = {
        "label": args.label,
        "endpoint": args.endpoint,
        "steps": args.steps,
        "runs": rows,
        "cold": {f: stats(cold, f) for f in ("delay_s", "exec_s", "wall_s")},
        "warm": {f: stats(warm, f) for f in ("delay_s", "exec_s", "wall_s")},
    }
    path = outdir / "results.json"
    path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print()
    print("images + results: %s" % outdir)

    return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except urllib.error.HTTPError as e:
        sys.exit("HTTP %s: %s" % (e.code, e.read().decode()[:300]))
    except KeyboardInterrupt:
        sys.exit(130)
