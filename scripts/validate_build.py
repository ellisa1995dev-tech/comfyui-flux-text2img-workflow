"""Build-time validation for the FLUX text2img serverless worker.

Checks, without a GPU, that the image can actually run the workflow:

  1. every model file the workflow names exists and is non-empty,
  2. ComfyUI imports cleanly (a custom node's requirements can drag a shared
     dependency past the version the base image pinned, which breaks the
     import and would otherwise surface on a live worker as the misleading
     "ComfyUI server not reachable"),
  3. every class_type used by the workflow is registered, i.e. the custom
     nodes really installed.

The failure summary is printed LAST, and deliberately so: build log viewers
truncate to the tail, so anything printed earlier can be cut off exactly when
it is needed most.
"""

import json
import logging
import os
import sys
import traceback

WORKFLOW = "/api-workflow.json"
COMFY_DIR = "/comfyui"

REQUIRED_MODELS = [
    "/comfyui/models/unet/flux1-dev.safetensors",
    "/comfyui/models/vae/ae.sft",
    "/comfyui/models/text_encoders/t5xxl_fp8_e4m3fn.safetensors",
    "/comfyui/models/text_encoders/clip_l.safetensors",
]

problems = []
notes = []


def summarize_and_exit():
    """Print the verdict as the final output, then exit."""
    print("", flush=True)
    print("=" * 72, flush=True)
    print("BUILD VALIDATION SUMMARY", flush=True)
    print("=" * 72, flush=True)
    for note in notes:
        print("  " + note, flush=True)
    if problems:
        print("", flush=True)
        print("FAILED - %d problem(s):" % len(problems), flush=True)
        for p in problems:
            for i, line in enumerate(str(p).splitlines()):
                print(("  * " if i == 0 else "    ") + line, flush=True)
        print("=" * 72, flush=True)
        sys.exit(1)
    print("", flush=True)
    print("PASSED - models present, ComfyUI imports, all node classes resolved", flush=True)
    print("=" * 72, flush=True)
    sys.exit(0)


# --- environment diagnostics ----------------------------------------------
for mod in ("torch", "transformers", "huggingface_hub", "numpy"):
    try:
        notes.append("%-16s %s" % (mod, __import__(mod).__version__))
    except Exception as exc:  # noqa: BLE001 - diagnostics must never abort
        notes.append("%-16s NOT IMPORTABLE (%s)" % (mod, exc))

try:
    import torch

    notes.append("%-16s %s" % ("torch cuda build", torch.version.cuda))
except Exception:  # noqa: BLE001
    pass

custom_nodes_dir = os.path.join(COMFY_DIR, "custom_nodes")
if os.path.isdir(custom_nodes_dir):
    installed = sorted(
        d for d in os.listdir(custom_nodes_dir)
        if os.path.isdir(os.path.join(custom_nodes_dir, d))
    )
    notes.append("custom_nodes    %s" % ", ".join(installed))

# --- 1. model files --------------------------------------------------------
for path in REQUIRED_MODELS:
    if not os.path.isfile(path):
        problems.append("missing model file: %s" % path)
    elif os.path.getsize(path) == 0:
        problems.append("empty model file: %s" % path)
    else:
        notes.append("model OK        %-52s %.2f GB"
                     % (path, os.path.getsize(path) / 1e9))

# --- 2. ComfyUI import -----------------------------------------------------
# Capture ComfyUI's own warnings; it logs "IMPORT FAILED: <dir>" per custom
# node that fails to load, which is the single most useful diagnostic here.
captured = []


class _Capture(logging.Handler):
    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if "IMPORT FAILED" in msg or "Cannot import" in msg:
            captured.append(msg.strip())


logging.getLogger().addHandler(_Capture())
logging.getLogger().setLevel(logging.INFO)

os.chdir(COMFY_DIR)
sys.path.insert(0, COMFY_DIR)
sys.argv = ["main.py", "--cpu"]

nodes = None
try:
    import nodes as _nodes

    nodes = _nodes
except Exception:  # noqa: BLE001
    problems.append(
        "ComfyUI failed to import. This breaks the worker at runtime, not just "
        "the build.\n" + traceback.format_exc()
    )
    summarize_and_exit()

# Load custom nodes. API nodes are skipped: this workflow uses none, and
# loading them only widens the surface for unrelated failures.
try:
    import asyncio
    import inspect

    try:
        result = nodes.init_extra_nodes(init_custom_nodes=True, init_api_nodes=False)
    except TypeError:
        result = nodes.init_extra_nodes()
    if inspect.isawaitable(result):
        asyncio.run(result)
except Exception:  # noqa: BLE001
    problems.append("init_extra_nodes() raised:\n" + traceback.format_exc())

for msg in captured:
    problems.append("custom node import failure: %s" % msg)

# --- 3. workflow node classes ---------------------------------------------
try:
    with open(WORKFLOW, "r", encoding="utf-8") as f:
        workflow = json.load(f)
except Exception:  # noqa: BLE001
    problems.append("could not read %s:\n%s" % (WORKFLOW, traceback.format_exc()))
    summarize_and_exit()

registered = set(getattr(nodes, "NODE_CLASS_MAPPINGS", {}))
required = sorted({n["class_type"] for n in workflow.values()})
missing = [c for c in required if c not in registered]

notes.append("node classes    %d required, %d registered in ComfyUI"
             % (len(required), len(registered)))
for cls in required:
    notes.append("  %-28s %s" % (cls, "OK" if cls in registered else "UNRESOLVED"))

if missing:
    problems.append("unresolved node classes: %s" % ", ".join(missing))

summarize_and_exit()
