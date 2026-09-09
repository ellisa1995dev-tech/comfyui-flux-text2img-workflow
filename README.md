# Flux Text2Img Workflow

ComfyUI FLUX text2img workflow packaged as a **RunPod Serverless** worker.
Originally Dockerized via [comfyui-wizard](https://comfy.getrunpod.io).
Submission: https://comfy.getrunpod.io/dashboard/submissions/kd75kjrc919rgm15nsnjdj6y2x8e3qk9

## Serverless API

Send a job to the endpoint's `/run` or `/runsync`:

```json
{
  "input": {
    "prompt": "a handsome boy, cyberpunk style, neon lights",
    "seed": 12345
  }
}
```

| Field    | Required | Notes |
| -------- | -------- | ----- |
| `prompt` | yes¹     | Replaces the text on the `CLIPTextEncode` node feeding `BasicGuider`. |
| `seed`   | no       | Written to the `Seed (rgthree)` node that drives `RandomNoise`. Random if omitted; the effective value is echoed back in the response. |
| `width`  | no       | Multiple of 8, 64–2048. Sets `EmptyLatentImage` directly (bypasses the aspect-ratio preset). |
| `height` | no       | As above. Provide together with `width`. |
| `steps`  | no       | 1–100, written to `BasicScheduler` (default 25). |
| `workflow` | no     | A full ComfyUI API-format graph, same as the stock `worker-comfyui` API. Any field above is applied on top of it. |

¹ Optional if you supply your own `workflow`, which already carries its prompt.

Response follows the stock `worker-comfyui` convention — base64 images by
default, or S3 URLs when the endpoint has `BUCKET_ENDPOINT_URL` configured:

```json
{
  "images": [{ "filename": "ComfyUI_00001_.png", "type": "base64", "data": "iVBORw0..." }],
  "seed": 12345
}
```

## Build it yourself

```bash
docker build -t my-comfy-workflow .
```

The default model URLs are ungated, so the build needs no token. To pull the
official (gated) Black Forest Labs weights instead, accept the licenses on
Hugging Face and pass your token plus the official URLs:

```bash
docker build \
  --build-arg HF_TOKEN=$HF_TOKEN \
  --build-arg FLUX_UNET_URL=https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors \
  --build-arg FLUX_VAE_URL=https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/ae.safetensors \
  -t my-comfy-workflow .
```

The on-disk filenames are fixed (`flux1-dev.safetensors`, `ae.sft`) so the
workflow resolves either way. Note the default UNET is the **fp8_e4m3fn** build
of FLUX.1-dev; the FLUX.1-dev license (non-commercial) applies regardless of
which mirror you download from.

Test locally without RunPod (needs an NVIDIA GPU):

```bash
docker run --rm --gpus all -e SERVE_API_LOCALLY=true -p 8000:8000 -p 8188:8188 my-comfy-workflow
curl -X POST http://localhost:8000/runsync -H 'Content-Type: application/json' -d @test_input.json
```

## Deploy on RunPod

1. Go to https://runpod.io/console/serverless and create a new endpoint
2. Choose **Import Git Repository**, pick this repo, branch `main`
3. RunPod detects `handler.py` (it contains `runpod.serverless.start`) and builds the Dockerfile
4. Pick a GPU with **≥ 24 GB VRAM** (FLUX fp8 + T5-XXL) and raise the container disk to **≥ 30 GB**
5. Send the request shape shown above

## Files

- `Dockerfile` — base `runpod/worker-comfyui:5.10.0-base`, plus custom nodes, models and serverless wiring
- `handler.py` — RunPod Serverless entrypoint; injects parameters, delegates to the stock worker handler
- `workflow.json` — the raw workflow, as designed in ComfyUI
- `api-workflow.json` — the same graph in ComfyUI's `/prompt` API shape (what the handler loads)
- `test_input.json` — sample job payload
