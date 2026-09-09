"""RunPod Serverless entrypoint for the FLUX text2img ComfyUI workflow.

This module is a thin parameter-injection layer in front of the handler that
ships inside `runpod/worker-comfyui:5.10.0-base`. The base image's start.sh
launches ComfyUI and then runs `python -u /handler.py`, so this file is
installed at /handler.py and the stock worker handler is moved aside to
/worker_comfyui_handler.py (see Dockerfile).

Everything the stock worker already does well is reused verbatim: ComfyUI
readiness polling, /prompt submission, websocket completion detection,
execution-error reporting and base64/S3 output packaging. This layer only:

  1. loads the repo's api-workflow.json,
  2. injects `prompt` / `seed` / `width` / `height` / `steps` into the nodes
     that actually control them (resolved by graph topology, not hard-coded
     node ids), and
  3. delegates to the stock handler.

Request shape:

    {"input": {"prompt": "a handsome boy, cyberpunk style, neon lights",
               "seed": 12345}}

A raw `workflow` may still be supplied, matching the stock worker's API; any
of the parameters above are then applied on top of it.
"""

import copy
import json
import os
import random

import runpod

# The stock worker-comfyui handler, moved aside by the Dockerfile. Its
# runpod.serverless.start() call is behind an `if __name__ == "__main__"`
# guard, so importing it does not start a second worker.
import worker_comfyui_handler

WORKFLOW_PATH = os.environ.get("WORKFLOW_PATH", "/api-workflow.json")

# "Seed (rgthree)" declares its INT widget with max 2**50, which is smaller
# than RandomNoise's own 2**64-1. Clamp to the tighter of the two so a large
# user seed is never rejected by ComfyUI's input validation.
MAX_SEED = 1125899906842624

# Latent geometry limits. Width/height must be multiples of 8 because
# EmptyLatentImage works in 8x-downscaled latent space.
MIN_DIM = 64
MAX_DIM = 2048
DIM_STEP = 8

_WORKFLOW_CACHE = None


def _load_workflow():
    """Load and cache the API-format workflow shipped with the image."""
    global _WORKFLOW_CACHE
    if _WORKFLOW_CACHE is None:
        with open(WORKFLOW_PATH, "r", encoding="utf-8") as f:
            _WORKFLOW_CACHE = json.load(f)
    return copy.deepcopy(_WORKFLOW_CACHE)


def _nodes_of_type(workflow, *class_types):
    """Return [(node_id, node)] for every node with one of the given classes."""
    return [
        (nid, node)
        for nid, node in workflow.items()
        if isinstance(node, dict) and node.get("class_type") in class_types
    ]


def _resolve_link(workflow, value):
    """Follow an API-format link (["<node_id>", slot]) to its source node.

    Returns (node_id, node) for a link, or (None, None) for a literal value.
    """
    if isinstance(value, list) and len(value) == 2 and str(value[0]) in workflow:
        nid = str(value[0])
        return nid, workflow[nid]
    return None, None


def _env_node(workflow, var):
    """Optional explicit node-id override via environment variable."""
    nid = os.environ.get(var)
    if nid and nid in workflow:
        return nid, workflow[nid]
    return None, None


# --------------------------------------------------------------------------
# Node resolution -- each helper finds the node that *actually* drives a value,
# following links rather than trusting widget defaults or node ids.
# --------------------------------------------------------------------------


def _find_prompt_node(workflow):
    """Find the CLIPTextEncode feeding the sampler's positive conditioning.

    Preference order: explicit override, then the encoder wired into
    BasicGuider/CFGGuider conditioning (FLUX has no negative branch here),
    then a lone CLIPTextEncode.
    """
    nid, node = _env_node(workflow, "PROMPT_NODE_ID")
    if node:
        return nid, node

    for _, guider in _nodes_of_type(workflow, "BasicGuider", "CFGGuider"):
        src_id, src = _resolve_link(
            workflow, guider.get("inputs", {}).get("conditioning")
        )
        if src is not None and "text" in src.get("inputs", {}):
            return src_id, src

    encoders = [
        (nid, n)
        for nid, n in _nodes_of_type(workflow, "CLIPTextEncode")
        if "text" in n.get("inputs", {})
    ]
    if len(encoders) == 1:
        return encoders[0]
    return None, None


def _find_seed_target(workflow):
    """Find the node/field that controls the final generation seed.

    The noise node's `noise_seed` is a *link* to a "Seed (rgthree)" node in
    this workflow, so writing to the noise node itself would have no effect --
    the link value wins. Follow the link to its source and write there.
    """
    nid, node = _env_node(workflow, "SEED_NODE_ID")
    if node:
        for field in ("seed", "noise_seed", "value"):
            if field in node.get("inputs", {}):
                return nid, node, field

    for noise_id, noise in _nodes_of_type(workflow, "RandomNoise"):
        value = noise.get("inputs", {}).get("noise_seed")
        src_id, src = _resolve_link(workflow, value)
        if src is not None:
            for field in ("seed", "noise_seed", "value"):
                if field in src.get("inputs", {}):
                    return src_id, src, field
        else:
            return noise_id, noise, "noise_seed"

    for nid, sampler in _nodes_of_type(workflow, "KSampler", "KSamplerAdvanced"):
        for field in ("seed", "noise_seed"):
            if field in sampler.get("inputs", {}):
                return nid, sampler, field

    return None, None, None


def _find_latent_node(workflow):
    """Find the empty-latent node that establishes the base resolution."""
    nid, node = _env_node(workflow, "LATENT_NODE_ID")
    if node:
        return nid, node
    found = _nodes_of_type(
        workflow, "EmptyLatentImage", "EmptySD3LatentImage", "EmptyLatentImagePresets"
    )
    return found[0] if len(found) == 1 else (None, None)


# --------------------------------------------------------------------------
# Input validation
# --------------------------------------------------------------------------


def _validate_dimension(name, value):
    """Coerce a width/height to a valid latent dimension or return an error."""
    try:
        dim = int(value)
    except (TypeError, ValueError):
        return None, "'{}' must be an integer".format(name)
    if dim < MIN_DIM or dim > MAX_DIM:
        return None, "'{}' must be between {} and {}".format(name, MIN_DIM, MAX_DIM)
    if dim % DIM_STEP:
        return None, "'{}' must be a multiple of {}".format(name, DIM_STEP)
    return dim, None


def _validate(job_input):
    """Validate this layer's parameters. Returns (params, error_message)."""
    if job_input is None:
        return None, "Please provide input"

    if isinstance(job_input, str):
        try:
            job_input = json.loads(job_input)
        except json.JSONDecodeError:
            return None, "Invalid JSON format in input"

    if not isinstance(job_input, dict):
        return None, "'input' must be a JSON object"

    params = {"workflow": job_input.get("workflow")}

    prompt = job_input.get("prompt")
    if prompt is not None:
        if not isinstance(prompt, str) or not prompt.strip():
            return None, "'prompt' must be a non-empty string"
        params["prompt"] = prompt

    # A prompt is required unless the caller supplied a complete workflow that
    # already carries its own prompt text.
    if "prompt" not in params and params["workflow"] is None:
        return None, "Missing 'prompt' parameter"

    seed = job_input.get("seed")
    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            return None, "'seed' must be an integer"
        if seed < 0:
            return None, "'seed' must be non-negative"
        params["seed"] = seed % (MAX_SEED + 1)

    for name in ("width", "height"):
        if job_input.get(name) is not None:
            value, error = _validate_dimension(name, job_input[name])
            if error:
                return None, error
            params[name] = value

    steps = job_input.get("steps")
    if steps is not None:
        try:
            steps = int(steps)
        except (TypeError, ValueError):
            return None, "'steps' must be an integer"
        if not 1 <= steps <= 100:
            return None, "'steps' must be between 1 and 100"
        params["steps"] = steps

    images = job_input.get("images")
    if images is not None:
        if not isinstance(images, list) or not all(
            isinstance(i, dict) and "name" in i and "image" in i for i in images
        ):
            return (
                None,
                "'images' must be a list of objects with 'name' and 'image' keys",
            )
    params["images"] = images
    params["comfy_org_api_key"] = job_input.get("comfy_org_api_key")

    return params, None


# --------------------------------------------------------------------------
# Injection
# --------------------------------------------------------------------------


def _apply_dimensions(workflow, width, height):
    """Set the base latent size and keep any latent rescale node consistent.

    In this workflow EmptyLatentImage's width/height are links from
    SDXLAspectRatioSelector, and the result is then resized by
    DF_Latent_Scale_to_side. Writing literal ints detaches the aspect-ratio
    preset (the now-unused node simply is not executed), and the rescale
    node's side_length is realigned so it does not undo the requested size.
    """
    nid, latent = _find_latent_node(workflow)
    if latent is None:
        return "Could not locate an empty-latent node to apply width/height"

    inputs = latent["inputs"]
    if width is not None:
        inputs["width"] = width
    if height is not None:
        inputs["height"] = height

    final_w = inputs.get("width")
    final_h = inputs.get("height")
    if not isinstance(final_w, int) or not isinstance(final_h, int):
        return "Width and height must both be provided for this workflow"

    # Realign the latent rescale so the requested resolution survives it.
    for _, scaler in _nodes_of_type(workflow, "DF_Latent_Scale_to_side"):
        side = str(scaler.get("inputs", {}).get("side", "Longest"))
        if side == "Longest":
            scaler["inputs"]["side_length"] = max(final_w, final_h)
        elif side == "Shortest":
            scaler["inputs"]["side_length"] = min(final_w, final_h)
        elif side == "Width":
            scaler["inputs"]["side_length"] = final_w
        elif side == "Height":
            scaler["inputs"]["side_length"] = final_h
    return None


def build_workflow(params):
    """Build the ComfyUI API-format workflow for this job.

    Returns (workflow, error_message).
    """
    workflow = params.get("workflow")
    if workflow is None:
        workflow = _load_workflow()
    else:
        if isinstance(workflow, str):
            try:
                workflow = json.loads(workflow)
            except json.JSONDecodeError:
                return None, "'workflow' is not valid JSON"
        if not isinstance(workflow, dict):
            return None, "'workflow' must be a JSON object in ComfyUI API format"
        workflow = copy.deepcopy(workflow)

    if "prompt" in params:
        nid, node = _find_prompt_node(workflow)
        if node is None:
            return None, "Could not locate the positive prompt node in the workflow"
        node["inputs"]["text"] = params["prompt"]

    # Always pin a seed so results are reproducible and reported back.
    seed = params.get("seed")
    if seed is None:
        seed = random.randint(0, MAX_SEED)
    nid, node, field = _find_seed_target(workflow)
    if node is None:
        return None, "Could not locate the seed node in the workflow"
    node["inputs"][field] = seed
    params["seed"] = seed

    if "width" in params or "height" in params:
        error = _apply_dimensions(workflow, params.get("width"), params.get("height"))
        if error:
            return None, error

    if "steps" in params:
        scheduler_nodes = _nodes_of_type(
            workflow, "BasicScheduler", "KSampler", "KSamplerAdvanced"
        )
        applied = False
        for _, node in scheduler_nodes:
            if "steps" in node.get("inputs", {}):
                node["inputs"]["steps"] = params["steps"]
                applied = True
        if not applied:
            return None, "Could not locate a node accepting 'steps' in the workflow"

    return workflow, None


def handler(job):
    """RunPod Serverless handler: inject parameters, then run the stock worker."""
    params, error = _validate(job.get("input"))
    if error:
        return {"error": error}

    workflow, error = build_workflow(params)
    if error:
        return {"error": error}

    # Hand off to the stock worker-comfyui handler, which owns the ComfyUI
    # lifecycle (readiness, queueing, completion, errors) and the output
    # format (base64 by default, S3 when BUCKET_ENDPOINT_URL is configured).
    delegated_job = {
        "id": job.get("id"),
        "input": {
            "workflow": workflow,
            "images": params.get("images"),
            "comfy_org_api_key": params.get("comfy_org_api_key"),
        },
    }

    result = worker_comfyui_handler.handler(delegated_job)

    # Echo the effective seed so a randomly chosen one can be reused.
    if isinstance(result, dict) and "error" not in result:
        result["seed"] = params["seed"]
    return result


if __name__ == "__main__":
    print("flux-text2img-worker - Starting handler...")
    runpod.serverless.start({"handler": handler})
