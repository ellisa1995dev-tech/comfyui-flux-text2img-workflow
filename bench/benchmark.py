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

# Quality suite: one prompt per failure mode we actually care about, each with
# a fixed seed so every model sees identical noise. Categories are the things
# that separate models -- faces, hands, counting, composition, long-prompt
# adherence -- not a random sample of pretty pictures.
#
# Seeds are distinct per prompt on purpose: repeating a (prompt, seed) pair on
# a warm worker returns ComfyUI's cached result in ~0.2s and silently corrupts
# any timing average built from it.
PROMPTS = [
    ("portrait",
     "close-up portrait of a 25-year-old woman, green eyes, dark brown hair, "
     "soft smile, cozy bedroom, natural window light", 1111),
    ("full-body",
     "full-body photograph of a woman in a long grey wool coat and boots, "
     "standing on a city street, entire figure visible head to toe", 2222),
    ("complex-background",
     "a woman reading at a cafe table, busy street market behind her with "
     "stalls, pedestrians, bicycles and hanging signs", 3333),
    ("multiple-objects",
     "exactly five ripe lemons and three green pears arranged on a wooden "
     "table beside a blue ceramic jug", 4444),
    ("difficult-composition",
     "low-angle wide shot of a spiral staircase seen from directly below, "
     "strong perspective, symmetrical framing", 5555),
    ("facial-detail",
     "extreme close-up of an elderly man's face, deep wrinkles, visible skin "
     "pores, individual eyelashes, catchlight in both eyes", 6666),
    ("hands",
     "close-up of two hands carefully tying a shoelace, all ten fingers "
     "clearly visible and correctly formed", 7777),
    ("clothing-detail",
     "detailed studio shot of an embroidered silk jacket on a mannequin, "
     "visible stitching, buttons and fabric weave", 8888),
    ("lighting",
     "portrait lit by a single candle in a dark room, strong chiaroscuro, "
     "warm falloff, deep shadows", 9999),
    ("long-prompt",
     "editorial photograph of a 30-year-old woman with shoulder-length auburn "
     "hair and freckles, wearing a tailored charcoal blazer over a cream silk "
     "blouse, standing three-quarter turned toward camera in a sunlit "
     "mid-century apartment, one hand resting on a walnut chair, warm "
     "late-afternoon light from a tall window on the left, shallow depth of "
     "field, 85mm lens, muted earth-tone palette, calm confident expression", 12345),
]


# Step counts swept in latency mode. Fitting exec_s against steps separates the
# per-step GPU cost from everything that happens once per request (text
# encoding, VAE decode, PNG encode, handler overhead) without needing any
# instrumentation inside ComfyUI.
STEP_SWEEP = (1, 2, 4, 8)


def build_plan(args):
    """Return (plan, step_plan): the request list and steps for each request.

    Every entry gets a unique seed. Repeating a (prompt, seed) pair on a warm
    worker hits ComfyUI's node cache and returns in ~0.2s without generating,
    which would quietly poison the timings.
    """
    if args.mode == "latency":
        prompt = PROMPTS[0][1]
        plan, step_plan, seed = [], [], 900000
        for rep in range(args.reps):
            for steps in STEP_SWEEP:
                seed += 1
                plan.append(("steps=%d/rep%d" % (steps, rep + 1), prompt, seed))
                step_plan.append(args.steps if args.steps is not None else steps)
        return plan, step_plan

    chosen = PROMPTS if args.runs <= 0 else PROMPTS[:args.runs]
    return list(chosen), [args.steps] * len(chosen)


def fit_step_cost(rows):
    """Least-squares fit of exec_s = fixed + per_step * steps over warm runs.

    Returns (fixed_s, per_step_s) or None when there is too little spread.
    """
    pts = [(r["steps_requested"], r["exec_s"]) for r in rows
           if r.get("ok") and r.get("steps_requested")]
    if len({p[0] for p in pts}) < 2:
        return None
    n = len(pts)
    sx = sum(p[0] for p in pts)
    sy = sum(p[1] for p in pts)
    sxx = sum(p[0] * p[0] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    per_step = (n * sxy - sx * sy) / denom
    fixed = (sy - per_step * sx) / n
    return fixed, per_step


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
    ap.add_argument("--label", default="run", help="name for this variant, e.g. dev / klein4b")
    ap.add_argument("--mode", choices=("quality", "latency"), default="quality",
                    help="quality: one run per category. latency: sweep steps to "
                         "separate per-step cost from fixed overhead")
    ap.add_argument("--runs", type=int, default=0,
                    help="quality mode: how many categories to run (default: all)")
    ap.add_argument("--reps", type=int, default=2,
                    help="latency mode: repetitions per step count (default 2)")
    ap.add_argument("--steps", type=int, default=None,
                    help="override steps; omit to use the workflow's own default")
    ap.add_argument("--out", default="bench/results", help="output directory")
    ap.add_argument("--interval", type=float, default=0.25, help="poll interval seconds")
    ap.add_argument("--timeout", type=float, default=600.0, help="per-job timeout seconds")
    args = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        sys.exit("RUNPOD_API_KEY is not set. Export it; do not pass it on the command line.")

    plan, step_plan = build_plan(args)

    base = "https://api.runpod.ai/v2/" + args.endpoint
    outdir = pathlib.Path(args.out) / args.label
    outdir.mkdir(parents=True, exist_ok=True)

    def steps_for(i):
        return step_plan[i]

    print("endpoint : %s" % args.endpoint)
    print("label    : %s" % args.label)
    print("mode     : %s" % args.mode)
    print("runs     : %d (sequential)" % len(plan))
    print("steps    : %s" % (args.steps if args.steps is not None else
                             ("sweep %s" % (STEP_SWEEP,) if args.mode == "latency"
                              else "workflow default")))
    print()
    print("  #  category               worker           delay    exec    wall")
    print("  " + "-" * 68)

    rows = []
    for i in range(args.runs):
        category, prompt, seed = plan[i]
        r = run_one(base, key, prompt, seed, steps_for(i), args.interval, args.timeout)
        r["run"] = i + 1
        r["category"] = category
        r["prompt"] = prompt
        r["seed"] = seed
        r["steps_requested"] = steps_for(i)

        if r.get("ok"):
            for n, img in enumerate(r.pop("images")):
                if img.get("type") != "base64":
                    print("     (image is %s, not base64 - not saved)" % img.get("type"))
                    continue
                name = "run%02d_%s_seed%d%s.png" % (i + 1, category, seed, "" if n == 0 else "_%d" % n)
                (outdir / name).write_bytes(base64.b64decode(img["data"]))
            print("  %2d  %-21s  %-14s  %6.2f  %6.2f  %6.2f"
                  % (r["run"], category[:21], (r.get("worker") or "?")[:14],
                     r["delay_s"], r["exec_s"], r["wall_s"]))
        else:
            print("  %2d  %-21s  %-14s  %s"
                  % (r["run"], (r.get("status") or "ERROR")[:21],
                     (r.get("worker") or "?")[:14], str(r.get("error"))[:50]))
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

    # Latency decomposition. exec_s is ComfyUI + handler; wall_s is what the
    # caller experiences. The gap between them is the API leg: submit, poll
    # granularity, and shipping the image back.
    fit = fit_step_cost(warm) if warm else None
    if warm:
        print()
        print("  LATENCY BREAKDOWN (warm)")
        api_leg = [r["wall_s"] - r["exec_s"] - r["delay_s"] for r in warm]
        print("    queue / worker pickup   %6.2f s" % statistics.fmean(r["delay_s"] for r in warm))
        print("    ComfyUI execution       %6.2f s" % statistics.fmean(r["exec_s"] for r in warm))
        print("    API leg (submit+poll+transfer) %6.2f s" % statistics.fmean(api_leg))
        print("    end-to-end              %6.2f s" % statistics.fmean(r["wall_s"] for r in warm))
        if fit:
            fixed, per_step = fit
            print()
            print("    fitted: exec = %.2fs fixed + %.3fs/step" % (fixed, per_step))
            print("      fixed  = text encode + VAE decode + PNG encode + handler")
            print("      /step  = GPU sampling cost")
            for s in (4, 8):
                print("      -> %d steps would sample in ~%.2fs (exec ~%.2fs)"
                      % (s, per_step * s, fixed + per_step * s))
        else:
            print()
            print("    (run with --mode latency to fit per-step vs fixed cost)")

    by_cat = {}
    for r in warm:
        if r.get("category"):
            by_cat.setdefault(r["category"], []).append(r["exec_s"])
    if len(by_cat) > 1:
        print()
        print("  PER-CATEGORY execution (warm)")
        for cat in sorted(by_cat):
            vals = by_cat[cat]
            print("    %-24s %6.2f s  (n=%d)" % (cat, statistics.fmean(vals), len(vals)))

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
