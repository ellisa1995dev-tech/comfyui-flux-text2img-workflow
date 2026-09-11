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
import http.client
import json
import os
import pathlib
import statistics
import sys
import time
import urllib.error
import urllib.parse
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
        # --steps would pin every run to one value while the labels still read
        # 1/2/4/8, producing a "sweep" whose execution time does not move with
        # steps. Refuse it rather than emit misleading labels.
        if args.steps is not None:
            raise SystemExit(
                "--steps cannot be combined with --mode latency: the sweep sets "
                "the step count itself.\n"
                "  For a sweep:            --mode latency\n"
                "  For a fixed step count: --mode quality --steps N")
        prompt = PROMPTS[0][1]
        plan, step_plan, seed = [], [], 900000
        for rep in range(args.reps):
            for steps in STEP_SWEEP:
                seed += 1
                plan.append(("steps%d-rep%d" % (steps, rep + 1), prompt, seed))
                step_plan.append(steps)
        return plan, step_plan

    if args.mode == "fixed":
        # Isolate text encoding inside the fixed cost. ComfyUI caches a node's
        # output on unchanged inputs, so CLIPTextEncode is skipped when the
        # prompt repeats. Half the runs reuse one prompt (encoder cached),
        # half use a fresh prompt each time (encoder runs). The difference in
        # exec_s is the text-encoder cost -- no ComfyUI instrumentation needed.
        plan, step_plan, seed = [], [], 800000
        fixed_prompt = PROMPTS[0][1]
        for rep in range(args.reps * 2):
            seed += 1
            plan.append(("cached-prompt", fixed_prompt, seed))
            step_plan.append(args.steps)
        for i in range(args.reps * 2):
            seed += 1
            cat, prompt, _ = PROMPTS[i % len(PROMPTS)]
            plan.append(("fresh-prompt-" + cat, prompt, seed))
            step_plan.append(args.steps)
        return plan, step_plan

    chosen = PROMPTS if args.runs <= 0 else PROMPTS[:args.runs]
    offset = getattr(args, "seed_offset", 0) or 0
    return ([(cat, prompt, seed + offset) for cat, prompt, seed in chosen],
            [args.steps] * len(chosen))


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


_CONNS = {}


def _conn_for(host, reuse):
    """One persistent HTTPS connection per host when reuse is on.

    urllib opens a fresh TCP+TLS connection per call. A 4s job polled every
    250ms means a dozen handshakes to api.runpod.ai, and that cost lands in
    the measured API leg. --no-reuse restores the old behaviour so the
    difference can be measured rather than assumed.
    """
    if not reuse:
        return http.client.HTTPSConnection(host, timeout=60)
    conn = _CONNS.get(host)
    if conn is None:
        conn = _CONNS[host] = http.client.HTTPSConnection(host, timeout=60)
    return conn


def api(url, key, payload=None, timeout=60, reuse=True):
    """POST when payload is given, else GET. Returns parsed JSON.

    Records timing and response size on the function object so run_one can
    attribute the API leg without changing every call site.
    """
    parts = urllib.parse.urlsplit(url)
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": "Bearer " + key}
    if body:
        headers["Content-Type"] = "application/json"

    started = time.monotonic()
    for attempt in (1, 2):
        conn = _conn_for(parts.netloc, reuse)
        try:
            conn.request("POST" if body else "GET", parts.path, body, headers)
            resp = conn.getresponse()
            raw = resp.read()
            break
        except (http.client.HTTPException, OSError):
            # A reused connection can be closed by the far end between calls.
            _CONNS.pop(parts.netloc, None)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            if attempt == 2:
                raise
    if not reuse:
        conn.close()

    api.last_elapsed = time.monotonic() - started
    api.last_bytes = len(raw)
    if resp.status >= 400:
        raise urllib.error.HTTPError(url, resp.status, raw[:300].decode("utf-8", "replace"),
                                     resp.getheaders(), None)
    return json.loads(raw.decode())


api.last_elapsed = 0.0
api.last_bytes = 0


def download(url, timeout=120):
    """Fetch an object-storage URL. Returns (bytes, seconds).

    No Authorization header: these are presigned URLs on a different host, and
    sending the RunPod key to a storage endpoint would leak it. The URL itself
    carries a signature, so it is never printed in full.
    """
    parts = urllib.parse.urlsplit(url)
    path = parts.path + (("?" + parts.query) if parts.query else "")
    started = time.monotonic()
    for attempt in (1, 2):
        conn = _conn_for(parts.netloc, True)
        try:
            conn.request("GET", path, None, {"Accept": "*/*"})
            resp = conn.getresponse()
            raw = resp.read()
            break
        except (http.client.HTTPException, OSError):
            _CONNS.pop(parts.netloc, None)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            if attempt == 2:
                raise
    if resp.status >= 400:
        raise RuntimeError("storage GET %s returned %s" % (parts.netloc, resp.status))
    return raw, time.monotonic() - started


def image_ext(blob, fallback_name=""):
    """Extension matching the actual bytes, not the declared name."""
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    if blob[:2] == b"\xff\xd8":
        return "jpg"
    return os.path.splitext(fallback_name)[1].lstrip(".") or "bin"


def run_one(base, key, prompt, seed, steps, interval, timeout, opts=None):
    """Submit one job and poll until it settles. Returns a result dict.

    Also attributes the API leg: submit round-trip, polling detection lag, and
    the download of the final response (which carries the base64 image). Those
    three are what sits between server-reported time and wall clock.
    """
    opts = opts or {}
    body = {"input": {"prompt": prompt, "seed": seed}}
    if steps is not None:
        body["input"]["steps"] = steps
    for k in ("width", "height", "output_format", "delivery"):
        if opts.get(k) is not None:
            body["input"][k] = opts[k]
    reuse = opts.get("reuse", True)

    started = time.monotonic()
    submitted = api(base + "/run", key, body, reuse=reuse)
    submit_s = api.last_elapsed
    job_id = submitted.get("id")
    if not job_id:
        return {"ok": False, "error": "no job id returned: %s" % submitted}

    deadline = started + timeout
    polls = 0
    last_poll_end = time.monotonic()
    while time.monotonic() < deadline:
        job = api("%s/status/%s" % (base, job_id), key, reuse=reuse)
        polls += 1
        status = job.get("status")

        if status == "COMPLETED":
            wall = time.monotonic() - started
            images = (job.get("output") or {}).get("images") or []
            # The final poll both detects completion and downloads the image;
            # its elapsed time is dominated by the payload, not by detection.
            final_s = getattr(api, "last_elapsed", 0.0)
            payload_bytes = getattr(api, "last_bytes", 0)
            server_s = (job.get("delayTime") or 0) / 1000.0 + \
                       (job.get("executionTime") or 0) / 1000.0
            return {
                "ok": True,
                "id": job_id,
                "status": status,
                "worker": job.get("workerId"),
                "delay_s": (job.get("delayTime") or 0) / 1000.0,
                "exec_s": (job.get("executionTime") or 0) / 1000.0,
                "wall_s": wall,
                "submit_s": submit_s,
                "final_poll_s": final_s,
                "payload_bytes": payload_bytes,
                "polls": polls,
                # Everything unaccounted for: detection lag plus RunPod's own
                # lag between finishing and reporting COMPLETED.
                "detect_s": max(0.0, wall - server_s - submit_s - final_s),
                "images": images,
                "seed_used": (job.get("output") or {}).get("seed"),
                "effective": (job.get("output") or {}).get("effective") or {},
                # Server-side stage timings reported by the handler.
                "encode_s": ((job.get("output") or {}).get("timings") or {}).get("encode_s"),
                "upload_s": ((job.get("output") or {}).get("delivery") or {}).get("upload_s"),
                "delivery_mode": ((job.get("output") or {}).get("delivery") or {}).get("mode")
                                 or "inline",
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
    ap.add_argument("--mode", choices=("quality", "latency", "fixed"), default="quality",
                    help="quality: one run per category. latency: sweep steps. "
                         "fixed: isolate text-encoding cost via ComfyUI's node cache")
    ap.add_argument("--runs", type=int, default=0,
                    help="quality mode: how many categories to run (default: all)")
    ap.add_argument("--reps", type=int, default=2,
                    help="latency mode: repetitions per step count (default 2)")
    ap.add_argument("--steps", type=int, default=None,
                    help="override steps; omit to use the workflow's own default")
    ap.add_argument("--out", default="bench/results", help="output directory")
    ap.add_argument("--interval", type=float, default=0.25, help="poll interval seconds")
    ap.add_argument("--timeout", type=float, default=600.0, help="per-job timeout seconds")
    ap.add_argument("--width", type=int, default=None, help="output width (multiple of 8)")
    ap.add_argument("--height", type=int, default=None, help="output height (multiple of 8)")
    ap.add_argument("--output-format", choices=("png", "webp", "jpeg"), default=None,
                    dest="output_format", help="ask the handler to re-encode the image")
    ap.add_argument("--seed-offset", type=int, default=0, dest="seed_offset",
                    help="shift every seed by N. Re-running the same suite on a "
                         "warm worker otherwise replays ComfyUI's node cache and "
                         "measures cache lookups instead of generation. Use a "
                         "different offset per configuration when comparing latency; "
                         "keep 0 when comparing images across models.")
    ap.add_argument("--delivery", choices=("inline", "url"), default=None,
                    help="inline: image returned as base64 in the response. "
                         "url: uploaded to object storage, response carries a link. "
                         "Omit to let the endpoint's own configuration decide.")
    ap.add_argument("--no-reuse", action="store_true",
                    help="open a new TLS connection per call (measures keep-alive benefit)")
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
    print("size     : %s" % ("%dx%d" % (args.width, args.height)
                             if args.width and args.height else "workflow default"))
    print("format   : %s" % (args.output_format or "handler default"))
    print("delivery : %s" % (args.delivery or "endpoint default"))
    print("seeds    : %s" % ("base" if not args.seed_offset
                             else "base+%d" % args.seed_offset))
    print("conn     : %s" % ("new per call" if args.no_reuse else "keep-alive"))
    print("steps    : %s" % (args.steps if args.steps is not None else
                             ("sweep %s" % (STEP_SWEEP,) if args.mode == "latency"
                              else "workflow default")))
    print()
    print("  #  category               worker           delay    exec    wall")
    print("  " + "-" * 68)

    rows = []
    # Iterate the plan, not --runs: in quality mode --runs is a cap that
    # defaults to 0 ("all categories"), and in latency mode it is unused.
    for i in range(len(plan)):
        category, prompt, seed = plan[i]
        r = run_one(base, key, prompt, seed, steps_for(i), args.interval, args.timeout,
                    opts={"width": args.width, "height": args.height,
                          "output_format": args.output_format,
                          "delivery": args.delivery,
                          "reuse": not args.no_reuse})
        r["run"] = i + 1
        r["category"] = category
        r["prompt"] = prompt
        r["seed"] = seed
        r["steps_requested"] = steps_for(i)

        if r.get("ok"):
            download_s, out_bytes = 0.0, 0
            for n, img in enumerate(r.pop("images")):
                kind = img.get("type")
                try:
                    if kind == "base64":
                        blob = base64.b64decode(img["data"])
                    elif kind == "s3_url":
                        # Fetch what the client would fetch, and time it
                        # separately from the server-side upload.
                        blob, dl = download(img["data"])
                        download_s += dl
                    else:
                        print("     (image type %s - not saved)" % kind)
                        continue
                except Exception as exc:  # noqa: BLE001
                    print("     (could not retrieve image: %s)" % exc)
                    continue

                out_bytes += len(blob)
                safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in category)
                # Name the file after what the bytes actually are: the handler
                # can return WEBP or JPEG, and writing those under a .png name
                # makes later analysis silently compare the wrong thing.
                name = "run%02d_%s_seed%d%s.%s" % (
                    i + 1, safe, seed, "" if n == 0 else "_%d" % n,
                    image_ext(blob, img.get("filename", "")))
                (outdir / name).write_bytes(blob)
            r["download_s"] = round(download_s, 3)
            r["output_bytes"] = out_bytes
            # What the customer actually waits for: response plus fetching the
            # image. For inline delivery the image is already in the response,
            # so download_s is zero and the two are the same.
            r["total_s"] = r["wall_s"] + download_s
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

    # Verify what the sampler actually ran. A step comparison is worthless if
    # the requested count never reached the node, and that failure is silent:
    # execution time simply stops tracking the label.
    verified, mismatched, unverifiable = [], [], []
    for r in rows:
        if not r.get("ok"):
            continue
        eff = (r.get("effective") or {}).get("steps")
        want = r.get("steps_requested")
        if eff is None:
            unverifiable.append(r)
        elif want is not None and eff != want:
            mismatched.append((r, want, eff))
        else:
            verified.append((r, eff))

    # Warm runs spread across several workers cannot be compared: each worker
    # is a different physical GPU, and RunPod endpoints may span GPU types.
    warm_workers = {}
    for r in warm:
        warm_workers.setdefault(r.get("worker"), []).append(r["exec_s"])
    if len(warm_workers) > 1:
        print()
        print("  *** WARM RUNS SPAN %d WORKERS - NOT COMPARABLE ***" % len(warm_workers))
        for w in sorted(warm_workers, key=lambda k: str(k)):
            vals = warm_workers[w]
            print("      %-18s n=%-3d exec mean %.2f s (%.2f-%.2f)"
                  % (str(w)[:18], len(vals), statistics.fmean(vals), min(vals), max(vals)))
        print("      Each worker is a different GPU. Pin the endpoint to one GPU")
        print("      type and re-run, or compare only runs sharing a workerId.")
    elif warm_workers:
        print()
        print("  all warm runs on one worker: %s" % str(next(iter(warm_workers)))[:18])

    # ComfyUI caches node outputs. Re-running the same prompts and seeds on a
    # warm worker replays that cache: execution collapses and the numbers look
    # spectacular while nothing was generated.
    steps_seen = {r.get("steps_requested") for r in warm if r.get("steps_requested")}
    if warm and len(steps_seen) == 1:
        steps_val = steps_seen.pop()
        mean_exec = statistics.fmean(r["exec_s"] for r in warm)
        floor = max(0.6, 0.30 * steps_val)
        if mean_exec < floor:
            print()
            print("  *** EXECUTION TOO FAST FOR %d STEPS - LIKELY CACHE HITS ***"
                  % steps_val)
            print("      warm execution averaged %.2f s (%.2f s/step)."
                  % (mean_exec, mean_exec / steps_val))
            print("      ComfyUI returns cached node outputs when the same prompt,")
            print("      seed and graph are submitted again to a warm worker, so this")
            print("      measures cache lookups rather than generation.")
            print("      Re-run with --seed-offset (e.g. --seed-offset 100000).")

    print()
    print("  EFFECTIVE SAMPLER SETTINGS")
    if mismatched:
        print("    *** STEP COUNT MISMATCH - DO NOT TRUST THIS COMPARISON ***")
        for r, want, eff in mismatched[:6]:
            print("      run %-3s %-22s requested=%s  actually ran=%s"
                  % (r["run"], r.get("category", "")[:22], want, eff))
    if unverifiable:
        print("    %d run(s) did not report effective settings." % len(unverifiable))
        print("    The deployed image predates the echo; rebuild to verify step counts.")
    if verified:
        seen = {}
        for r, eff in verified:
            seen.setdefault(eff, []).append(r["exec_s"])
        for eff in sorted(seen):
            print("    steps=%-3s confirmed on %d run(s), exec mean %.2f s"
                  % (eff, len(seen[eff]), statistics.fmean(seen[eff])))
        sample = verified[0][0].get("effective") or {}
        extras = ", ".join("%s=%s" % (k, sample[k]) for k in
                           ("cfg", "sampler_name", "scheduler", "width", "height")
                           if k in sample)
        if extras:
            print("    %s" % extras)

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

        def avg(field):
            vals = [r[field] for r in warm if r.get(field) is not None]
            return statistics.fmean(vals) if vals else None

        for field, lbl in (("submit_s", "submit round-trip"),
                           ("detect_s", "completion detection"),
                           ("final_poll_s", "final poll + image download")):
            v = avg(field)
            if v is not None:
                print("       %-28s %6.2f s" % (lbl, v))
        pb = avg("payload_bytes")
        if pb:
            print("       %-28s %6.2f MB (%d polls avg)"
                  % ("response payload", pb / 1e6, avg("polls") or 0))

        # Server-side stages the handler reports, plus the client fetch.
        modes = {r.get("delivery_mode") for r in warm}
        print("    delivery mode           %s" % ", ".join(sorted(str(m) for m in modes)))
        for field, lbl in (("encode_s", "WebP encode (server)"),
                           ("upload_s", "object-storage upload"),
                           ("download_s", "client download")):
            v = avg(field)
            if v:
                print("       %-28s %6.2f s" % (lbl, v))
        ob = avg("output_bytes")
        if ob:
            print("       %-28s %6.2f MB" % ("image size", ob / 1e6))

        print("    API response            %6.2f s" % statistics.fmean(r["wall_s"] for r in warm))
        tot = avg("total_s")
        if tot:
            print("    END-TO-END (incl. fetch)%6.2f s" % tot)
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
