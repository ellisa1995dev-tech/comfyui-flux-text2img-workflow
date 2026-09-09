# clean base image containing only comfyui, comfy-cli and comfyui-manager
FROM runpod/worker-comfyui:5.10.0-base

# build-time tokens for gated downloads — never baked into final image.
# pass via: docker build --build-arg HF_TOKEN=$HF_TOKEN ...
ARG HF_TOKEN=""

# model sources — defaults are ungated so the image builds with no token.
# override to pull the official (gated) Black Forest Labs weights, e.g.:
#   --build-arg HF_TOKEN=$HF_TOKEN \
#   --build-arg FLUX_UNET_URL=https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors \
#   --build-arg FLUX_VAE_URL=https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/ae.safetensors
# the on-disk filenames stay fixed so the workflow keeps resolving either way.
ARG FLUX_UNET_URL="https://huggingface.co/Kijai/flux-fp8/resolve/main/flux1-dev-fp8-e4m3fn.safetensors"
ARG FLUX_VAE_URL="https://huggingface.co/camenduru/FLUX.1-dev/resolve/main/ae.sft"

# install custom nodes into comfyui
RUN comfy node install --exit-on-fail rgthree-comfy --mode remote
RUN comfy node install --exit-on-fail comfyui-art-venture
# provides DF_Latent_Scale_to_side (Derfuu_ComfyUI_ModdedNodes)
RUN comfy node install --exit-on-fail derfuu_comfyui_moddednodes

# download models into comfyui
RUN BACKOFFS="10 20 30 60 90" && for i in 1 2 3 4 5; do HF_TOKEN=$HF_TOKEN comfy model download --url 'https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors' --relative-path models/text_encoders --filename 't5xxl_fp8_e4m3fn.safetensors' && break; if [ $i -eq 5 ]; then echo "model-download failed after 5 attempts" >&2; exit 1; fi; SLEEP=$(echo $BACKOFFS | cut -d ' ' -f $i) && echo "model-download attempt $i failed; retrying in $SLEEP seconds" >&2; sleep $SLEEP; done
RUN BACKOFFS="10 20 30 60 90" && for i in 1 2 3 4 5; do HF_TOKEN=$HF_TOKEN comfy model download --url 'https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors' --relative-path models/text_encoders --filename 'clip_l.safetensors' && break; if [ $i -eq 5 ]; then echo "model-download failed after 5 attempts" >&2; exit 1; fi; SLEEP=$(echo $BACKOFFS | cut -d ' ' -f $i) && echo "model-download attempt $i failed; retrying in $SLEEP seconds" >&2; sleep $SLEEP; done
# the flux diffusion model + vae the workflow needs (not present in the base image)
RUN BACKOFFS="10 20 30 60 90" && for i in 1 2 3 4 5; do HF_TOKEN=$HF_TOKEN comfy model download --url "$FLUX_UNET_URL" --relative-path models/unet --filename 'flux1-dev.safetensors' && break; if [ $i -eq 5 ]; then echo "model-download failed after 5 attempts" >&2; exit 1; fi; SLEEP=$(echo $BACKOFFS | cut -d ' ' -f $i) && echo "model-download attempt $i failed; retrying in $SLEEP seconds" >&2; sleep $SLEEP; done
RUN BACKOFFS="10 20 30 60 90" && for i in 1 2 3 4 5; do HF_TOKEN=$HF_TOKEN comfy model download --url "$FLUX_VAE_URL" --relative-path models/vae --filename 'ae.sft' && break; if [ $i -eq 5 ]; then echo "model-download failed after 5 attempts" >&2; exit 1; fi; SLEEP=$(echo $BACKOFFS | cut -d ' ' -f $i) && echo "model-download attempt $i failed; retrying in $SLEEP seconds" >&2; sleep $SLEEP; done

# serverless wiring.
# start.sh (from the base image) already boots ComfyUI and then runs
# `python -u /handler.py`, so the stock worker handler is moved aside and
# imported by ours as a library — no CMD/ENTRYPOINT override needed.
RUN test -f /handler.py && mv /handler.py /worker_comfyui_handler.py
COPY api-workflow.json /api-workflow.json
COPY handler.py /handler.py
COPY test_input.json /test_input.json

# build-time validation: every class_type used by the workflow must be
# registered by ComfyUI (proves the custom nodes really installed), and every
# model file the workflow names must exist. Runs on CPU — no GPU required.
RUN set -eu; \
    for f in /comfyui/models/unet/flux1-dev.safetensors \
             /comfyui/models/vae/ae.sft \
             /comfyui/models/text_encoders/t5xxl_fp8_e4m3fn.safetensors \
             /comfyui/models/text_encoders/clip_l.safetensors; do \
      [ -s "$f" ] || { echo "missing model file: $f" >&2; exit 1; }; \
    done; \
    cd /comfyui && python -c "\
import asyncio, json, sys;\
sys.argv = ['main.py', '--cpu'];\
import nodes;\
r = nodes.init_extra_nodes();\
asyncio.run(r) if asyncio.iscoroutine(r) else None;\
wf = json.load(open('/api-workflow.json'));\
missing = sorted({n['class_type'] for n in wf.values()} - set(nodes.NODE_CLASS_MAPPINGS));\
print('unresolved node classes:', missing) if missing else print('all workflow node classes resolved');\
sys.exit(1 if missing else 0)"
