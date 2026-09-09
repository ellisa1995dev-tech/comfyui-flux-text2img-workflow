# FLUX Text2Img — Serverless API

Integration reference for the RunPod Serverless endpoint built from this repo.

Turns a text prompt into a 1024×1024 PNG using FLUX.1-dev on ComfyUI.

| | |
| --- | --- |
| **Base URL** | `https://api.runpod.ai/v2/<ENDPOINT_ID>` |
| **Auth** | `Authorization: Bearer <RUNPOD_API_KEY>` |
| **Content type** | `application/json` |
| **Returns** | PNG as base64 (or an S3 URL, if configured) |

> **Credentials.** The endpoint ID and API key are **not** stored in this repo.
> Get the endpoint ID from the RunPod console (it also appears in the endpoint's
> request URLs). Create an API key under **RunPod → Settings → API Keys** and
> supply it to the service as an environment variable, e.g. `RUNPOD_API_KEY`,
> through your secret store. Never commit it, and never send it over chat or email.

> **The API key must stay server-side.** A browser or mobile client calling RunPod
> directly would have to ship the key, exposing the account and its GPU credit.
> Route image requests through your own backend.

---

## Endpoints

| Route | Purpose |
| --- | --- |
| `POST /run` | Submit a job, returns immediately with an id. **Use this in production.** |
| `GET /status/{id}` | Poll a job's state and collect its output. |
| `POST /runsync` | Submit and wait. Manual testing only — see [Timing](#timing). |
| `POST /cancel/{id}` | Cancel a queued or running job. |
| `GET /health` | Worker and queue health. |

---

## Request

All parameters go inside `input`. Only `prompt` is required.

```json
{
  "input": {
    "prompt": "a handsome boy, cyberpunk style, neon lights",
    "seed": 12345
  }
}
```

| Field | Type | Default | Constraints |
| --- | --- | --- | --- |
| `prompt` | string | **required** | Non-empty. The positive prompt. |
| `seed` | integer | random | `0`–`1125899906842624`. Negative values are rejected; larger values wrap modulo the maximum. |
| `width` | integer | `1024` | `64`–`2048`, multiple of 8. |
| `height` | integer | `1024` | `64`–`2048`, multiple of 8. |
| `steps` | integer | `25` | `1`–`100`. Lower is faster and cheaper, at lower quality. |

Either dimension may be given on its own; the other keeps its default.

Validation runs before any GPU work, so a malformed request fails fast, costs
nothing, and returns a specific message such as `'width' must be a multiple of 8`.

### Advanced (optional)

| Field | Type | Notes |
| --- | --- | --- |
| `workflow` | object | A complete ComfyUI API-format graph, submitted as sent. The fields above are applied on top of it. When using this, supply `width` and `height` together or neither. |
| `images` | array | Input images as `{"name", "image"}` (base64) for workflows that need them. Unused by the default text-to-image graph. |

---

## Response

The handler's return value arrives under `output`; RunPod adds the envelope.

### Completed

```json
{
  "id": "2c78151f-be7c-4968-a9be-3f6e37064774-e1",
  "status": "COMPLETED",
  "delayTime": 14070,
  "executionTime": 34310,
  "workerId": "w7sj5rfawxndg7",
  "output": {
    "images": [
      {
        "filename": "ComfyUI_00001_.png",
        "type": "base64",
        "data": "iVBORw0KGgoAAAANSUhEUg..."
      }
    ],
    "seed": 12345
  }
}
```

`delayTime` and `executionTime` are milliseconds.

`seed` is always the seed actually used, so a randomly chosen one can be replayed.

| Key | Notes |
| --- | --- |
| `output.images[].data` | Raw base64 PNG, **no** `data:` URI prefix. |
| `output.images[].type` | `base64`, or `s3_url` if S3 upload is configured — then `data` holds a URL, not bytes. Branch on this rather than assuming. |
| `output.images[].filename` | ComfyUI's filename, e.g. `ComfyUI_00001_.png`. |
| `output.seed` | The effective seed. |
| `output.errors` | **Present only on partial success:** images were produced but something went wrong too. Log it. |
| `output.status` | Present only as `"success_no_images"` — the workflow ran but produced no image. Treat as a failure rather than returning a broken image. |

### Failed

```json
{
  "id": "570c1b2b-e4a3-41d0-aea7-15ac74367e19-e2",
  "status": "FAILED",
  "error": "'width' must be a multiple of 8"
}
```

**Branch on `status`, never on the presence of `output`.**

On failure the message is at the **top level** as `error`, not inside `output`.
The RunPod SDK lifts the handler's `error` out of the returned object and drops
`output` entirely when nothing else remains — so a validation failure has **no**
`output` key at all. A workflow that failed mid-run may additionally carry
`output.details` with per-step diagnostics.

### Decoding the image

```js
// Node
const buf = Buffer.from(job.output.images[0].data, "base64");
```

```python
# Python
buf = base64.b64decode(job["output"]["images"][0]["data"])
```

Treat `images` as a list even though it currently holds a single entry.

---

## The integration flow

Submit, poll, decode.

### 1. Submit

`POST /run` returns immediately with an id and status `IN_QUEUE`.

```js
const BASE = `https://api.runpod.ai/v2/${process.env.RUNPOD_ENDPOINT_ID}`;

const res = await fetch(`${BASE}/run`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${process.env.RUNPOD_API_KEY}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ input: { prompt, seed } }),
});
const { id } = await res.json();
```

### 2. Poll until it settles

`GET /status/{id}`. Keep polling while the status is `IN_QUEUE` or `IN_PROGRESS`;
stop on anything else (`COMPLETED`, `FAILED`, `CANCELLED`, `TIMED_OUT`).

```js
async function waitFor(id, { intervalMs = 2000, timeoutMs = 300000 } = {}) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const res = await fetch(`${BASE}/status/${id}`, {
      headers: { Authorization: `Bearer ${process.env.RUNPOD_API_KEY}` },
    });
    const job = await res.json();

    if (job.status === "COMPLETED") return job;
    if (job.status !== "IN_QUEUE" && job.status !== "IN_PROGRESS") {
      throw new Error(job.error ?? `job ${job.status}`);
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error("timed out waiting for image");
}
```

A 2-second interval is a sensible start. Polling faster does not speed up generation.

### 3. Store the result, return a URL

Decode the base64 into your own storage (whatever the product already uses) and
hand the client a URL. Passing ~1 MB of base64 through your own API to the
browser wastes bandwidth on both hops and is awkward to cache.

---

## Timing

Measured on a real completed job, not estimated.

| Measure | Observed | Meaning |
| --- | --- | --- |
| Cold start (`delayTime`) | 14.07 s | Waiting for a worker. Near zero when one is already warm. |
| Generation (`executionTime`) | 34.31 s | 25 steps at 1024×1024. Scales roughly with `steps`. |
| Total observed | ~48 s | Budget a timeout well above this; 5 minutes is a safe ceiling. |
| PNG size | 776 KB | 1024×1024. |
| Base64 in response | ~1.03 MB | Base64 inflates bytes by ~33%. Don't log the response body. |

RunPod's return-body limit is **20 MB**, so a single image uses roughly 5% of the
budget. Many images in one response, or much larger ones, would approach it.

**Design the UX around ~50 seconds, not 5.** This is not a request a user can wait
on synchronously. Submit, return a job id to the client immediately, and deliver
the image once it lands. Use `/run` and poll rather than `/runsync`, whose long
held-open connection invites gateway timeouts on a cold start.

---

## Errors worth handling

| Symptom | Cause | Handling |
| --- | --- | --- |
| `401` | Missing or invalid API key | Configuration error — fail at startup, not per request. |
| `FAILED` + `error` | Rejected input, or the workflow could not run | Log the message. Input errors are deterministic; retrying will not help. |
| `TIMED_OUT` | Exceeded the endpoint's execution timeout | Safe to retry once. If routine, lower `steps` or raise the endpoint timeout. |
| Long `IN_QUEUE` | Workers busy or scaling from zero | Expected. Keep polling; raise max workers if routine. |
| `COMPLETED`, empty `images` | Workflow produced nothing (`output.status` is `success_no_images`) | Rare. Treat as a failure. |
| `COMPLETED` + `output.errors` | Partial success | Image is usable; log the warnings. |

---

## Before you scale

- **Every request costs GPU-seconds.** Put authentication and a per-user rate
  limit in front of the endpoint before it is reachable from the product.
- **Consider returning URLs instead of base64.** Setting `BUCKET_ENDPOINT_URL`
  and S3 credentials on the RunPod endpoint makes the worker upload directly and
  return `"type": "s3_url"`, removing ~1 MB from every response.
- **Idle timeout is the cold-start dial.** A longer idle timeout keeps workers
  warm and cuts the 14-second delay, at the cost of paying for idle time.
- **Prompts are user input.** This endpoint applies no moderation.
- **FLUX.1-dev is licensed for non-commercial use.** Confirm licensing before
  shipping commercially.

---

## Verification

Request fields, response shapes, and the error mapping in this document were
verified against the deployed handler ([`handler.py`](../handler.py)), the
`runpod/worker-comfyui:5.10.0` handler it delegates to, and the RunPod SDK's
job-result mapping (`rp_job.py`), plus two real jobs observed on the live
endpoint — one `COMPLETED`, one `FAILED`.

Timings come from a single observed run and will vary with GPU type and queue depth.
