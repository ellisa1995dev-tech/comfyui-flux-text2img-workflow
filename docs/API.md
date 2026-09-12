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
| **Output** | 1024×1024 PNG, base64 in the response |
| **Warm latency** | **~4.1 s** end-to-end (measured; see [Timing](#timing)) |
| **Cold start** | ~26 s |
| **Licence** | Apache-2.0 — commercial use permitted |

> **Credentials.** The endpoint ID and API key are **not** in this repo. Get the
> endpoint ID from the RunPod console; create an API key under **RunPod →
> Settings → API Keys** and supply it to the service as an environment variable
> (`RUNPOD_API_KEY`) from your secret store. Never commit it, never send it over
> chat or email.

> **The API key must stay server-side.** A browser or mobile client calling
> RunPod directly would have to ship the key, exposing the account and its GPU
> credit. Route image requests through your own backend.

---

## 1. Recommended configuration

Start here. The rest of the document is reference.

```jsonc
POST /run
{
  "input": {
    "prompt": "close-up portrait of a 25-year-old woman, green eyes, soft smile",
    "seed": 12345
    // no output_format  -> PNG, ComfyUI's native output, no re-encode
    // no delivery       -> inline base64
  }
}
```

Then poll `GET /status/{id}` until the status settles.

| Choice | Why |
| --- | --- |
| **PNG** (omit `output_format`) | ComfyUI writes PNG natively. Asking for lossless WebP costs **0.73 s** of re-encode to save ~0.4 MB — a net loss. Both are lossless; PNG is simply free. |
| **Inline** (omit `delivery`) | Measured **~2 s faster** than S3 URLs, and your backend stores the image in its own bucket anyway. |
| **`/run` + poll** | `/runsync` measured only **0.08 s** faster — inside the noise. Polling avoids long-held connections and needs one code path, not two. |
| **4 steps** | **Do not change.** See [Quality](#quality). |

---

## 2. Endpoints

| Route | Purpose |
| --- | --- |
| `POST /run` | Submit a job, returns immediately with an id. **Use this.** |
| `GET /status/{id}` | Poll a job's state and collect its output. |
| `POST /runsync` | Submit and wait in one round trip. See the note below. |
| `POST /cancel/{id}` | Cancel a queued or running job. |
| `GET /health` | Worker and queue health. |

> **On `/runsync`:** it works and is marginally faster, but RunPod falls back to
> async when a job outruns its sync window — so you must implement polling
> anyway. Given that, `/run` + poll is one code path instead of two, for 0.08 s.

---

## 3. Request

Use **one** of `prompt` or `requirements`.

### Simple: a prompt

```json
{
  "input": {
    "prompt": "close-up portrait of a 25-year-old woman, green eyes, dark brown hair, soft smile, natural window light",
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

The composed prompt is returned in `output.prompt`, so you can log exactly what
reached the model. An unknown field is **rejected with the list of valid ones**,
so a typo fails loudly rather than silently dropping a requirement.

### All fields

| Field | Type | Default | Notes |
| --- | --- | --- | --- |
| `prompt` | string | — | The positive prompt. Required unless `requirements` is given. |
| `requirements` | object | — | Structured fields, composed into a prompt. Ignored if `prompt` is also sent. |
| `prompt_suffix` | string | — | Appended to the prompt. For house style, without touching customer fields. |
| `seed` | integer | random | `0`–`1125899906842624`. Negative rejected; larger values wrap. Always echoed back. |
| `width` | integer | `1024` | `64`–`2048`, multiple of 8. |
| `height` | integer | `1024` | `64`–`2048`, multiple of 8. |
| `steps` | integer | `4` | `1`–`100`. **Leave at 4.** |
| `output_format` | string | `png` | `png`, `webp` (lossless), `jpeg`. Leave unset. |
| `delivery` | string | auto | `inline` or `url`. Leave unset unless storage is configured. |

### Advanced

| Field | Type | Notes |
| --- | --- | --- |
| `workflow` | object | A complete ComfyUI API-format graph, submitted as sent. Fields above are applied on top. |
| `images` | array | Input images as `{"name", "image"}` (base64), for graphs that consume them. |

**Validation runs before any GPU work**, so a malformed request fails in
milliseconds and costs nothing.

---

## 4. Response

### Completed

```json
{
  "id": "6e21437c-76eb-48b1-95e2-be5d170e1aa8-e1",
  "status": "COMPLETED",
  "delayTime": 130,
  "executionTime": 1960,
  "workerId": "w75gl0kmglualq",
  "output": {
    "images": [
      { "filename": "klein4b_00001_.png", "type": "base64", "data": "iVBORw0KGgo..." }
    ],
    "seed": 12345,
    "prompt": "a 25-year-old woman, green eyes, ... . editorial photography.",
    "effective": {
      "steps": 4, "cfg": 1, "sampler_name": "euler",
      "scheduler": "simple", "width": 1024, "height": 1024, "batch_size": 1
    },
    "timings": { "encode_s": 0.0 }
  }
}
```

`delayTime` and `executionTime` are **milliseconds**.

| Key | Notes |
| --- | --- |
| `output.images[].type` | `base64` or `s3_url`. **Branch on this**, don't assume. |
| `output.images[].data` | Raw base64, no `data:` prefix — or an https URL when `type` is `s3_url`. |
| `output.images[].filename` | e.g. `klein4b_00001_.png`. |
| `output.seed` | The seed actually used. Replay it to reproduce the image exactly. |
| `output.prompt` | The composed prompt, when `requirements` was used. |
| `output.effective` | What the sampler actually ran — useful for asserting config in staging. |
| `output.timings` | Server-side stage timings (`encode_s`, `upload_s`). |
| `output.errors` | Partial success — image produced, but something also went wrong. Log it. |
| `output.status` | Only ever `"success_no_images"`. Treat as a failure. |

### Failed

```json
{
  "id": "6e21437c-...",
  "status": "FAILED",
  "error": "'width' must be a multiple of 8"
}
```

**Branch on `status`, never on the presence of `output`.** On failure the
message is at the **top level** as `error`. The SDK lifts it out of the returned
object and drops `output` when nothing else remains, so a validation failure has
**no `output` key at all**. A workflow that failed mid-run additionally carries
`output.details` with per-step diagnostics — log those; they name the real cause.

### Decoding

```js
// Node
const buf = Buffer.from(job.output.images[0].data, "base64");
```

```python
# Python
buf = base64.b64decode(job["output"]["images"][0]["data"])
```

Treat `images` as a list even though it holds one entry today.

---

## 5. Integration flow

```
Client                Your backend                    RunPod
  │                        │                             │
  ├─ POST /generate ──────▶│                             │
  │   {requirements}       ├─ POST /run ────────────────▶│   (API key here only)
  │                        │◀─ {id} ─────────────────────┤
  │◀─ {job_id} ────────────┤                             │
  │   (your id, not RunPod's)                            │
  │                        ├─ poll /status/{id} ────────▶│
  │                        │◀─ COMPLETED + base64 ───────┤
  │                        ├─ decode, store in YOUR bucket
  ├─ GET /jobs/{job_id} ──▶│
  │◀─ {status, image_url} ─┤
```

### 1. Submit

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

```js
async function waitFor(id, { intervalMs = 250, timeoutMs = 120000 } = {}) {
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
inflates latency — we measured it. A 250 ms interval is a sensible default;
polling faster does not speed up generation.

### 3. Store and return your own URL

Decode into your own bucket and hand the client a URL you control — lifecycle,
CDN and access control all stay yours.

### What your backend should own

- **Its own job IDs.** Don't leak RunPod's; it keeps the client contract stable
  if the provider ever changes.
- **The state record:** job id, requirements, the returned `seed`, status, image
  URL. The seed is what makes a result reproducible.
- **Auth and rate limiting.** Every request costs GPU-seconds.

---

## 6. Timing

Measured on **RTX 4090**, 9 warm runs, 4 steps, 1024×1024, PNG inline.

| Stage | Warm | Share |
| --- | --- | --- |
| Queue / worker pickup | 0.13 s | 3% |
| **ComfyUI execution (generation)** | **1.96 s** | 47% |
| API leg (submit + poll + transfer) | 2.10 s | 50% |
| **End-to-end** | **4.19 s** | |

Per-category execution ranged **1.55–2.44 s**; long prompts cost slightly more
because text encoding scales with token count.

Cold start (first request after idle): **~26 s** — ~12–16 s worker pickup plus
~8–11 s loading ~12.5 GB of weights into VRAM.

> **The API leg was measured from a UK client.** Your backend is in the US, much
> closer to the workers, so **expect it to be materially lower** — the 2.10 s
> includes transferring a ~2 MB response across the Atlantic. Measure it from
> your own environment before quoting a latency figure; end-to-end under 4 s is
> plausible for a US backend and was not achievable from the UK.

`/runsync` measured 4.11 s versus 4.19 s for `/run` + poll — a 0.08 s
difference, which is why this document recommends polling for simplicity.

---

## 7. Concurrency and cost

A worker handles **one job at a time**, and is occupied for `executionTime`
(~1.96 s warm).

**Workers needed ≈ arrival rate × generation time.**

| Load | Workers |
| --- | --- |
| 1 request/s | ~2 |
| 200 requests over 60 s | ~7 |
| 2,500 images as a batch | 1 GPU ≈ 82 min; 5 GPUs ≈ 16 min; 10 GPUs ≈ 8 min |

At $1.10/hr for an RTX 4090, that is **~$0.0006 per image** — 2,500 images for
about **$1.50**.

**Cold starts are the tail risk, not throughput.** A request arriving after idle
waits ~26 s. Keep at least one active worker during traffic hours, and enable
**FlashBoot** on the endpoint.

For bulk generation, `batch_size` on the latent node amortises per-request fixed
costs across several images — worth benchmarking if you have batch workloads.

---

## 8. Errors worth handling

| Symptom | Cause | Handling |
| --- | --- | --- |
| `401` / `403` | Key missing, revoked, scoped to other endpoints, or wrong endpoint id | Configuration error — fail at startup, not per request. |
| `FAILED` + `error` | Rejected input, or the workflow could not run | Log it, plus `output.details`. Input errors are deterministic; retrying will not help. |
| `FAILED` + `delivery='url' requires object storage...` | Endpoint lacks `BUCKET_*` variables | Omit `delivery` to use inline. |
| `TIMED_OUT` | Exceeded the endpoint's execution timeout | Safe to retry once. |
| Long `IN_QUEUE` | Workers busy or scaling from zero | Expected. Keep polling; raise max workers if routine. |
| `COMPLETED`, empty `images` | Workflow produced nothing (`output.status` = `success_no_images`) | Rare. Treat as a failure. |

---

## 9. Quality

**Do not lower `steps` below 4.** The customer compared 2-step and 4-step output
and chose 4: facial detail — moles, skin texture — is visibly better and less
blurred. 4 steps is also Black Forest Labs' reference setting for this model.

**Do not change the resolution** from 1024×1024, or the sampler from
`euler` / `simple` / CFG 1.0. Klein is a *distilled* model; raising CFG or steps
fights the distillation rather than improving output.

There is **no upscaler, face restoration, sharpening or second pass**. PNG
output is lossless, so nothing alters the pixels after generation. If a request
ever returns an image that looks softened, that is a generation result, not
post-processing.

Generation is **deterministic**: the same prompt and seed produce a
byte-identical image.

---

## 10. Verification

Request and response shapes were verified against the deployed handler, the
`runpod/worker-comfyui:5.10.0` handler it delegates to, and the RunPod SDK's
job-result mapping. Timings come from repeated warm runs on a single worker and
vary with GPU type, region and queue depth.

To assert configuration from your own integration tests, check
`output.effective` — it reports what the sampler actually ran, read back from
the submitted graph, independent of what was requested:

```json
"effective": { "steps": 4, "cfg": 1, "sampler_name": "euler",
               "scheduler": "simple", "width": 1024, "height": 1024 }
```

A staging assertion on those six values will catch any accidental change to the
production baseline.
