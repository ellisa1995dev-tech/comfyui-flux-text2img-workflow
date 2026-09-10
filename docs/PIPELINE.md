# Production image pipeline — design and model selection

Target: high-quality, prompt-faithful, subject-consistent images at roughly
**3 seconds**, on RunPod Serverless, at scale.

**Status: designed and implemented, not yet benchmarked.** No claim below that
depends on a measurement is presented as measured. The two numbers that *are*
measured come from the existing endpoints and are labelled as such.

---

## 1. Model selection

### Recommendation: FLUX.2 [klein] 4B (distilled)

Weighed against the stated priorities:

| Priority | klein 4B | Basis |
| --- | --- | --- |
| Image quality | ? | BFL claim "state-of-the-art"; **must benchmark** |
| Prompt adherence | Likely improved | Qwen3-4B LLM text encoder vs FLUX.1's T5-XXL + CLIP-L |
| Subject consistency | Native | Multi-reference editing built into the model |
| Speed | Strong | 4B params, **4 steps**, cfg 1.0 (BFL reference config) |
| VRAM | ~13 GB | Runs on RTX 3090/4070 class and up |
| Scalability | Strong | fp8 weights total ~8 GB → cheaper GPUs, more workers per £ |
| Licensing | **Apache-2.0** | Commercial use permitted |

### Why not the alternatives

| Model | Verdict | Reason |
| --- | --- | --- |
| FLUX.2 klein **9B** | **Disqualified** | Non-commercial licence — BFL's card states 4B is Apache-2.0 and 9B is non-commercial |
| FLUX.2 **dev** | Disqualified | Non-commercial, and larger |
| FLUX.2 klein-**base** 4B | Wrong tool | Undistilled: BFL's reference uses **50 steps**, guidance 4.0 — ~12× the sampling cost. Keep it in mind only if we ever train a character LoRA |
| FLUX.1-dev (current) | Superseded | 31.5 s warm (measured), non-commercial, known waxy-skin weakness |
| FLUX.1-schnell | Superseded | 5.9 s warm (measured), but older-generation quality |
| Z-Image Turbo | **Benchmark as challenger** | 6B, Apache-2.0, ~8 steps, RunPod ships a recipe. Legitimate alternative |
| SDXL + Juggernaut | Fallback | Very fast, mature photoreal ecosystem, but older-generation prompt adherence |

Klein 4B is *not* recommended because it is newest. It is recommended because
it is the only current-generation FLUX that is commercially licensed, and it is
distilled to 4 steps — the licence and the step count are what matter here.

**Z-Image Turbo should be benchmarked alongside it.** If klein 4B's realism
disappoints, Z-Image is the next candidate, not FLUX.1.

---

## 2. The workflow

`bench/api-workflow-klein4b.json` — nine nodes, every one load-bearing.

```
UNETLoader ─┐
CLIPLoader ─┼─► CLIPTextEncode ─┬─────────────► KSampler ─► VAEDecode ─► SaveImage
VAELoader ──┘                   └─ ConditioningZeroOut ─┘        ▲
                                 EmptyFlux2LatentImage ──────────┘
```

### Optimisation decisions

**One text-encoder pass, not two.** The negative branch is produced by
`ConditioningZeroOut` on the positive conditioning rather than by encoding a
second prompt. The text encoder is a 4B LLM; a second pass would be one of the
most expensive things in the graph and buys nothing here.

**cfg = 1.0.** Klein is guidance-distilled. At cfg 1.0 ComfyUI skips the
unconditional model pass entirely — that is **half the model evaluations per
step**, not a small saving. Raising cfg above 1.0 would double sampling cost
*and* fight the distillation.

**4 steps.** BFL's own reference implementation for klein 4B uses
`num_inference_steps=4, guidance_scale=1.0`. Step count is the single largest
latency lever; the benchmark sweeps 1/2/4/8 to find where quality plateaus.

**fp8 weights.** 4.07 GB instead of 7.75 GB — halves cold-start read and
resident VRAM. An fp4 text encoder (3.85 GB vs 8.04 GB) exists but wants
Blackwell-class hardware, so it is a build-arg override, not the default.

**No upscaler, no second pass, no face restoration.** Deliberately excluded
per the brief. Each would add seconds. They get added only if the benchmark
shows the base model failing on faces or detail — and then measured.

**Nothing installed that the graph does not execute.** The klein image
installs no custom nodes at all; every node is core ComfyUI.

### What was removed relative to the current production workflow

| Removed | Why |
| --- | --- |
| `SDXLAspectRatioSelector` | A lookup table returning 1024×1024. Replaced by direct width/height |
| `DF_Latent_Scale_to_side` | Rescaled the latent to a fixed longest side — redundant once dimensions are set directly |
| `Seed (rgthree)` | An indirection to hold a seed the handler sets anyway |
| `rgthree-comfy`, `art-venture`, `derfuu` | No longer needed → smaller image, faster cold start, three fewer import-failure risks |
| `SamplerCustomAdvanced` + 4 helper nodes | Replaced by a single `KSampler` |

15 nodes and 3 custom-node packages → **9 nodes, zero custom packages**.

---

## 3. Requirement → prompt pipeline

The API accepts structured fields and composes them **verbatim**:

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

Composed into three sentences, in weight order:

> a 25-year-old woman, green eyes, dark brown hair, a grey wool coat, standing
> three-quarter turned toward camera, a soft smile. a sunlit mid-century
> apartment, ... . editorial photography, muted earth tones, no jewellery.

**Design rules:**

- **Customer text is never reworded, reordered within a field, or dropped.**
  Grouping into sentences is the only transformation.
- **Sentence prose, not tag soup.** FLUX.2's encoder is an LLM; BFL's card
  warns "prompt following is heavily influenced by the prompting style."
- **No LLM prompt-enhancement step.** It would add 200 ms–2 s to a 3 s budget
  and can silently drop requirements — the opposite of the goal. If enhancement
  is wanted later, do it offline and cache, not in the request path.
- **Escape hatches:** an explicit `prompt` overrides composition entirely;
  `prompt_suffix` appends house style without touching customer fields.
- Unknown fields are **rejected with the list of valid ones**, so a typo like
  `subjekt` fails loudly instead of silently dropping a requirement.

Note: at cfg 1.0 a negative prompt has **no effect** — the uncond pass is
skipped. Steering must be done positively.

---

## 4. Subject consistency

Three mechanisms, in increasing strength:

1. **Deterministic seeds** — same prompt + seed ⇒ identical image. Already
   verified: a repeated (prompt, seed) pair returned in 0.169 s from ComfyUI's
   cache, i.e. bit-identical.
2. **Reference images** (klein's native multi-reference editing) — `LoadImage
   → VAEEncode → ReferenceLatent` spliced into the conditioning chain. This is
   the mechanism the customer's own 9B workflow uses. **Designed, not yet
   implemented** — it is the next increment.
3. **Character LoRA** — train on klein-**base**-4B (undistilled, Apache-2.0,
   intended for fine-tuning), apply via `LoraLoaderModelOnly`. Strongest
   consistency, requires a training pipeline.

---

## 5. The 3-second target

### Latency budget

| Stage | How it is measured | Notes |
| --- | --- | --- |
| Request overhead | `wall − exec − delay` | Submit + poll granularity + transfer |
| Queue / cold start | `delayTime` | ~0 warm; 13–25 s cold (measured) |
| Model load | cold `exec` − warm `exec` | Once per worker, not per request |
| Text encoding | fit intercept | Part of "fixed" |
| Sampling | fit slope × steps | The GPU term |
| VAE decode | fit intercept | Part of "fixed" |
| Image encode | fit intercept | PNG; WEBP option in handler |
| API response | `wall` | End to end |

`bench/benchmark.py --mode latency` sweeps steps 1/2/4/8 and least-squares fits
`exec = fixed + per_step × steps`. That separates the GPU term from everything
that happens once per request **without instrumenting ComfyUI**. Validated
against synthetic data: it recovers known coefficients exactly.

Three numbers are reported separately, and must not be conflated:

- **GPU sampling** = `per_step × steps` (fitted)
- **ComfyUI execution** = `executionTime`
- **API end-to-end** = wall clock from submit to image in hand

### Is 3 seconds reachable?

From the measured FLUX.1 fit on the current GPU — `exec ≈ 1.03 s + 1.22 s/step`
— the fixed term alone is ~1 s and per-step is 1.22 s at 12B. If per-step scales
roughly with parameters, 4B lands near **0.4 s/step**, so 4 steps ≈ 1.6 s
sampling + ~1 s fixed ≈ **2.6 s ComfyUI execution**, plus the API leg.

That is an **extrapolation from one fitted model, not a measurement.** It says
the target is plausible, not that it is met.

**GPU class:** 1.22 s/step at 12B is slow — consistent with an A5000/L40S-class
card rather than H100. If klein 4B on the current GPU lands above 3 s, the next
lever is hardware, and the same benchmark on an H100 endpoint answers it in one
run.

### Reducing the API leg

- Poll interval dropped from 1 s to **0.25 s** (was adding ~0.5 s average).
- `output_format: "webp"` re-encodes in the handler — a 1024² PNG is ~1 MB
  base64; WEBP is several times smaller.
- **Production should use S3** (`BUCKET_ENDPOINT_URL`): the worker uploads
  directly and returns a URL, taking the image off the API leg entirely.

---

## 6. Quality benchmark

`bench/benchmark.py --mode quality` runs ten categories, each with a fixed seed,
identical across every model:

`portrait`, `full-body`, `complex-background`, `multiple-objects`,
`difficult-composition`, `facial-detail`, `hands`, `clothing-detail`,
`lighting`, `long-prompt`.

Seeds are unique per prompt **on purpose**: repeating a (prompt, seed) pair on a
warm worker returns ComfyUI's cached result in ~0.2 s and silently corrupts any
timing average built from it. This bit us once already.

Timing, VRAM and resolution are machine-measurable. **Prompt adherence, facial
quality, artefact rate and character consistency are human judgements** — the
harness lays out matched image pairs for scoring; it does not score them itself.

---

## 7. Production considerations

| Concern | Handling |
| --- | --- |
| Cold start | ~8 GB of fp8 weights vs ~17 GB today; keep ≥1 active worker for latency-sensitive hours |
| Warm execution | ComfyUI caches loaders between requests; the graph reloads nothing |
| Concurrency | One job per GPU. Workers ≈ arrival-rate × generation-time |
| Timeouts | Client-side bounded polling; endpoint execution timeout separate |
| Failed jobs | `status` FAILED with top-level `error` — see `docs/API.md` |
| Determinism | Seed always echoed; same seed + prompt ⇒ identical image |
| Output | base64 PNG default; WEBP option; S3 URLs recommended at scale |
| Horizontal scaling | Smaller VRAM footprint → cheaper GPU tiers → more workers per unit spend |

---

## 8. What is not yet proven

1. **klein 4B has not been built or run.** No image exists yet.
2. **No quality comparison exists.** Every quality statement above is a claim
   from BFL's model card or an inference from architecture.
3. **The 3-second figure is an extrapolation**, from a two-point fit on a
   different model.
4. **Reference-image consistency is designed, not implemented.**
5. **The GPU class in use is unconfirmed** — it materially affects everything.

Running `bench/benchmark.py` in both modes against a klein 4B endpoint and the
current one closes 1–3 in an afternoon.
