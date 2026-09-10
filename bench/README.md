# Benchmarks — FLUX.1-dev vs FLUX.1-schnell

Everything here is for measurement only. **Nothing in this directory changes the
production endpoint.** The root `Dockerfile`, `api-workflow.json`, `workflow.json`
and `handler.py` are untouched.

The question: can generation land near 3 seconds, and what does it cost in
quality to get there?

## Why a separate image

`steps` is already a request parameter, so it is tempting to just send
`{"steps": 4}` to the existing endpoint. That would measure the wrong thing.
FLUX.1-**dev** is not distilled for few-step sampling — at 4 steps it produces
visibly degraded images. FLUX.1-**schnell** is trained for exactly that.

A fair comparison therefore needs schnell's weights, which means a second image
and a second endpoint.

## What differs

`bench/api-workflow-schnell.json` is generated from the production workflow with
exactly two fields changed:

| Node | Field | Production | Benchmark |
| --- | --- | --- | --- |
| 149 `UNETLoader` | `unet_name` | `flux1-dev.safetensors` | `flux1-schnell.safetensors` |
| 17 `BasicScheduler` | `steps` | 25 | 4 |

Same node ids, same graph, same sampler, same VAE and text encoders (dev and
schnell share one autoencoder). `bench/Dockerfile.schnell` likewise differs from
the root Dockerfile in three functional lines: the UNET URL, the downloaded
filename, and the workflow it bundles.

The model is the single variable. That is the point.

> **Deliberately not changed:** the scheduler stays `normal`. ComfyUI's own
> schnell template prefers `simple`, which may suit schnell better — but
> changing it here would confound the comparison. Treat it as a follow-up knob
> once the model question is settled.

## 1. Benchmark the current production endpoint

Do this first. It costs nothing new and gives the warm baseline we still lack.

```bash
export RUNPOD_API_KEY=...          # from your secret store; never commit it
python bench/benchmark.py --endpoint <PROD_ENDPOINT_ID> --label dev
```

The script sends requests **one at a time**, waiting for each to finish. That
matters: concurrent requests make RunPod start a separate worker per job, and
every one of them pays the full cold cost. All five of the earlier measurements
ran on five different workers, which is why none of them measured the warm path.

Each run is classified by the worker that served it — first job on a worker is
COLD, any later job on the same worker is WARM — so the split comes from the
data rather than from assuming run 1 is the only cold one.

**Before running, raise the endpoint's idle timeout** (60s or more). Otherwise
the worker is torn down between requests and every run is cold again. If that
happens the script says so instead of reporting a misleading average.

## 2. Deploy the schnell variant

Create a **second** RunPod endpoint — do not modify the production one:

1. Serverless → New Endpoint → Import Git Repository → this repo, branch `main`
2. Set **Dockerfile path** to `/bench/Dockerfile.schnell`
3. **Choose the same GPU type as production** — otherwise the comparison is meaningless
4. Same container disk (≥ 30 GB) and idle timeout as step 1

## 3. Benchmark it identically

```bash
python bench/benchmark.py --endpoint <SCHNELL_ENDPOINT_ID> --label schnell
```

Same prompts, same seeds, same GPU. Images land in `bench/results/<label>/` for
side-by-side quality review, alongside a `results.json` with the timings.

## Reading the result

Three things decide it, and only the first is a pure number:

- **Warm execution time.** The headline figure. Compare `WARM → execution`.
- **Quality.** Open the five image pairs. Same prompt, same seed, different
  model. This is a judgement call and belongs to the client, not the benchmark.
- **Cold start.** Roughly the same for both — the weights are nearly identical
  in size (11.89 GB vs 11.90 GB), so schnell shortens generation, not loading.
  Only warm workers fix cold start.

## What this cannot tell you

The benchmark measures one GPU serving one request at a time. It says nothing
about concurrency: with one job per GPU, serving N simultaneous users needs
roughly `arrival_rate × generation_time` workers. Cutting generation time cuts
that fleet proportionally, which is the real reason the 3-second target and the
GPU bill are the same conversation.

## Licensing footnote

FLUX.1-dev is licensed for **non-commercial** use; FLUX.1-schnell is
**Apache-2.0**. If the product is commercial, schnell resolves a licensing
problem as well as a latency one — worth weighing alongside the image quality.
