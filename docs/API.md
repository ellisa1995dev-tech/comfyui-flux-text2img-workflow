# FLUX.2 Text2Img — Serverless API

Integration reference for the RunPod Serverless endpoint built from this repo.

Turns a text prompt, or a set of structured requirements, into a **1024×1024
image** using **FLUX.2 [klein] 4B** on ComfyUI.

| | |
| --- | --- |
| **Base URL** | `https://api.runpod.ai/v2/<ENDPOINT_ID>` |
| **Auth** | `Authorization: Bearer <RUNPOD_API_KEY>` |
| **Content type** | `application/json` |
| **Model** | FLUX.2 [klein] 4B (fp8), Qwen3-4B text encoder |
| **Sampling** | 4 steps, CFG 1.0, euler / simple |
| **Output** | 1024×1024, base64 image — or an object-storage URL |

> **Credentials.** The endpoint ID and API key are **not** in this repo. Get the
> endpoint ID from the RunPod console; create an API key under **RunPod →
> Settings → API Keys** and give it to the service as an environment variable
> (`RUNPOD_API_KEY`) from your secret store. Never commit it, never send it over
> chat or email.

> **The API key must stay server-side.** A browser or mobile client calling
> RunPod directly would have to ship the key, exposing the account and its GPU
> credit. Route image requests through your own backend.

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

Two ways to describe the image. Use **one** of `prompt` or `requirements`.

### Simple: a prompt

```json
{
  "input": {
    "prompt": "close-up portrait of a 25-year-old woman, green eyes, soft smile, natural window light",
    "seed": 12345
  }
}
```

### Structured: customer requirements

Thirteen optional fields. Values are copied **verbatim** — never reworded,
reordered within a field, or dropped — and grouped into sentences, because the
text encoder is an LLM and reads prose better than comma-separated tags.

```json
{
  "input": {
    "requirements": {
      "subject": "a 25-year-old woman",
      "appearance": "green eyes, dark brown hair",
      "clothing": "a grey wool coat",
      "pose": "standing three-quarter turned toward camera",
      "expression": "a soft smile",
      "environment": "a sunlit mid-century apartment",
      "background": "a tall window and walnut furniture",
      "lighting": "warm late-afternoon light from the left",
      "camera": "85mm lens, shallow depth of field",
      "composition": "head-and-shoulders framing",
      "style": "editorial photography",
      "color": "muted earth tones",
      "notes": "no jewellery"
    },
    "seed": 12345
  }
}
```

The composed prompt is returned in the response, so you can log exactly what was
sent to the model. An unknown field is **rejected with the list of valid ones**,
so a typo fails loudly instead of silently dropping a requirement.

### All fields

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `prompt` | string | — | The positive prompt. Required unless `requirements` is given. |
| `requirements` | object | — | Structured fields, composed into a prompt. Ignored if `prompt` is also sent. |
| `prompt_suffix` | string | — | Appended to the prompt. For house style, without touching customer fields. |
| `seed` | integer | random | `0`–`1125899906842624`. Negative rejected; larger values wrap. Always echoed back. |
| `width` | integer | `1024` | `64`–`2048`, multiple of 8. |
| `height` | integer | `1024` | `64`–`2048`, multiple of 8. |
| `steps` | integer | `4` | `1`–`100`. **Leave at 4** — see [Quality](#quality). |
| `output_format` | string | see below | `png`, `webp` (lossless), or `jpeg`. |
| `delivery` | string | auto | `inline` (base64 in the response) or `url` (object storage). |

`output_format` defaults to `webp` for URL delivery and `png` for inline.
**WebP here is lossless** — pixel-identical to the PNG, about 32% smaller.

### Advanced

| Field | Type | Notes |
| --- | --- | --- |
| `workflow` | object | A complete ComfyUI API-format graph, submitted as sent. Fields above are applied on top. |
| `images` | array | Input images as `{"name", "image"}` (base64), for graphs that consume them. |

---

## Response

### Completed

```json
{
  "id": "cade7f83-dab9-4d5e-8cb9-77aaf9abd145-e2",
  "status": "COMPLETED",
  "delayTime": 130,
  "executionTime": 3650,
  "workerId": "45iijguoudetkf",
  "output": {
    "images": [
      { "filename": "klein4b_00001_.webp", "type": "base64", "data": "UklGR..." }
    ],
    "seed": 12345,
    "prompt": "a 25-year-old woman, green eyes, ... . editorial photography.",
    "effective": {
      "steps": 4, "cfg": 1.0, "sampler_name": "euler",
      "scheduler": "simple", "width": 1024, "height": 1024
    },
    "timings": { "encode_s": 0.12 }
  }
}
```

`delayTime` and `executionTime` are milliseconds.

| Key | Notes |
| --- | --- |
| `output.images[].type` | `base64` or `s3_url`. **Branch on this**, don't assume. |
| `output.images[].data` | Raw base64 (no `data:` prefix) — or an https URL when `type` is `s3_url`. |
| `output.seed` | The seed actually used. Replay it to reproduce the image exactly. |
| `output.prompt` | The composed prompt, when `requirements` was used. |
| `output.effective` | What the sampler actually ran. Useful for asserting config in staging. |
| `output.timings` | Server-side stage timings (`encode_s`, `upload_s`). |
| `output.delivery` | Present for URL delivery: `mode`, `upload_s`, `bytes`, `format`. |
| `output.errors` | Partial success — image produced, but something also went wrong. Log it. |
| `output.status` | Only ever `"success_no_images"`. Treat as a failure. |

### Failed

```json
{
  "id": "cade7f83-...",
  "status": "FAILED",
  "error": "'width' must be a multiple of 8"
}
```

**Branch on `status`, never on the presence of `output`.** On failure the
message is at the **top level** as `error`. The SDK lifts it out of the returned
object and drops `output` when nothing else remains, so a validation failure has
**no** `output` key at all.

### Decoding

```js
// Node — inline
const buf = Buffer.from(job.output.images[0].data, "base64");
```

```python
# Python — inline
buf = base64.b64decode(job["output"]["images"][0]["data"])
```

For `type: "s3_url"`, `data` is a presigned https URL — fetch it directly, no
auth header. Treat `images` as a list even though it holds one entry today.

---

## The integration flow

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

Keep polling while `IN_QUEUE` or `IN_PROGRESS`; stop on anything else.

```js
async function waitFor(id, { intervalMs = 500, timeoutMs = 300000 } = {}) {
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

**Use a keep-alive HTTP agent.** A fresh TLS handshake per poll measurably
inflates latency — we measured it.

### 3. Store the result, return a URL

Decode into your own storage and hand the client a URL. Passing ~1.2 MB of
base64 through your own API to the browser wastes bandwidth twice and is
awkward to cache.

---

## Timing

Measured on a warm worker, 4 steps, 1024×1024.

| Stage | Warm |
| --- | --- |
| Queue / worker pickup | 0.13 s |
| ComfyUI execution | ~3.7 s |
| API leg (submit + poll + transfer) | 1.4–2.2 s |
| **End-to-end** | **5.5–6.0 s** |

Cold start (first request after idle): **~26 s** — 9.9 s worker pickup plus
13.9 s loading ~12.5 GB of weights into VRAM.

The API leg varies with payload: lossless WebP (~1.2 MB) is faster than PNG
(~1.5 MB). Roughly `0.74 s + 0.34 s/MB`, so there is a fixed ~1.3 s floor from
RunPod's submit and poll round-trips that no payload change removes.

**Design the UX around ~6 seconds, and ~26 s for a cold first request.** This is
not a request a user can wait on synchronously. Submit, return a job id
immediately, deliver the image when it lands. Use `/run` + poll, not `/runsync`,
whose long held-open connection invites gateway timeouts on a cold start.

> Timings were measured before the most recent image rebuild. The generation
> path (model, 4 steps, 1024×1024) is unchanged; encoding and delivery options
> were added since, so the API-leg figure will shift with `output_format`.

---

## Quality

**Do not lower `steps` below 4.** The customer compared 2-step and 4-step output
and chose 4: facial detail — moles, skin texture — is visibly better and less
blurred. 4 steps is also Black Forest Labs' reference setting for this model.

There is no upscaler, face restoration, sharpening or second pass. The image you
receive is what the model produced, and WebP output is lossless, so nothing
alters the pixels after generation.

---

## Errors worth handling

| Symptom | Cause | Handling |
| --- | --- | --- |
| `401` | Missing or invalid API key | Configuration error — fail at startup, not per request. |
| `FAILED` + `error` | Rejected input, or the workflow could not run | Log it. Input errors are deterministic; retrying will not help. |
| `FAILED` + `delivery='url' requires object storage...` | Endpoint lacks `BUCKET_*` variables | Configuration, not code. Omit `delivery` to fall back to inline. |
| `TIMED_OUT` | Exceeded the endpoint's execution timeout | Safe to retry once. |
| Long `IN_QUEUE` | Workers busy or scaling from zero | Expected. Keep polling; raise max workers if routine. |
| `COMPLETED`, empty `images` | Workflow produced nothing (`output.status` = `success_no_images`) | Rare. Treat as a failure. |

---

## Before you scale

- **Every request costs GPU-seconds.** Put authentication and a per-user rate
  limit in front of the endpoint before it is reachable from the product.
- **Concurrency:** one job per GPU. Workers ≈ arrival-rate × generation-time.
  At ~3.7 s execution, 200 requests over 60 s needs roughly 14 workers.
- **FlashBoot** on the endpoint cuts the ~26 s cold start substantially, at no
  extra cost.
- **Prompts are user input.** This endpoint applies no moderation.
- **Licensing:** FLUX.2 [klein] 4B is **Apache-2.0** — commercial use permitted.

---

## Verification

Request and response shapes were verified against the deployed handler, the
`runpod/worker-comfyui:5.10.0` handler it delegates to, and the RunPod SDK's
job-result mapping. Timings come from repeated warm runs on a single worker;
they vary with GPU type and queue depth.

To assert configuration from your own integration tests, check `output.effective`
— it reports what the sampler actually ran, independent of what was requested.
