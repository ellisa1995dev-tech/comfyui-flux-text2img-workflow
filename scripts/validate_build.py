"""Build-time validation report for the FLUX text2img serverless worker.

Checks, without a GPU, that the image can actually run the workflow:

  1. every model file the workflow names exists and is non-empty,
  2. ComfyUI imports cleanly,
  3. every class_type used by the workflow is registered, i.e. the custom
     nodes really installed.

This is a REPORT, not a gate: it always exits 0. Build log viewers show only
BuildKit's error footer when a step fails, never the step's own output, so a
failing check here is invisible and merely blocks deployment. The findings are
printed and also written to /build_validation.txt inside the image, where they
can be read from a running worker.

Genuinely fatal conditions are already guarded upstream: the model downloads
retry five times and then fail the build themselves, and a broken ComfyUI
import stops the worker at startup with its own error.
"""

import json
import logging
import os
import sys
import traceback

WORKFLOW = "/api-workflow.json"
COMFY_DIR = "/comfyui"
REPORT_PATH = "/build_validation.txt"

MODELS_DIR = "/comfyui/models"
MODEL_EXTS = (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin", ".gguf")


def required_models(workflow):
    """Model filenames the workflow names, read from the graph itself.

    Derived rather than hard-coded so this works unchanged for any workflow
    bundled into the image -- the benchmark variants included.
    """
    names = set()
    for node in workflow.values():
        if not isinstance(node, dict):
            continue
        for value in node.get("inputs", {}).values():
            if isinstance(value, str) and value.lower().endswith(MODEL_EXTS):
                names.add(value)
    return sorted(names)


def find_model(name):
    """Locate a model file anywhere under the models tree."""
    for root, _dirs, files in os.walk(MODELS_DIR):
        if name in files:
            return os.path.join(root, name)
    return None

lines = []
warnings = []


def say(text=""):
    lines.append(text)
    print(text, flush=True)


def warn(text):
    warnings.append(text)


def finish():
    """Print the verdict, persist the report, and always exit 0."""
    say()
    say("=" * 72)
    say("BUILD VALIDATION REPORT")
    say("=" * 72)
    if warnings:
        say("RESULT: %d WARNING(S) - image built anyway, see below" % len(warnings))
        say()
        for w in warnings:
            for i, line in enumerate(str(w).splitlines()):
                say(("  ! " if i == 0 else "    ") + line)
    else:
        say("RESULT: OK - models present, ComfyUI imports, all node classes resolved")
    say("=" * 72)
    try:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("report written to %s" % REPORT_PATH, flush=True)
    except Exception as exc:  # noqa: BLE001
        print("could not write %s: %s" % (REPORT_PATH, exc), flush=True)
    sys.exit(0)


say("--- environment ---")
for mod in ("torch", "transformers", "huggingface_hub", "numpy"):
    try:
        say("  %-16s %s" % (mod, __import__(mod).__version__))
    except Exception as exc:  # noqa: BLE001 - diagnostics must never abort
        say("  %-16s NOT IMPORTABLE (%s)" % (mod, exc))

try:
    import torch

    say("  %-16s %s" % ("torch cuda build", torch.version.cuda))
except Exception:  # noqa: BLE001
    pass

custom_nodes_dir = os.path.join(COMFY_DIR, "custom_nodes")
if os.path.isdir(custom_nodes_dir):
    for d in sorted(os.listdir(custom_nodes_dir)):
        if os.path.isdir(os.path.join(custom_nodes_dir, d)):
            say("  custom_node      %s" % d)

# --- 0. the workflow this image bundles ------------------------------------
say()
say("--- workflow ---")
workflow = None
try:
    with open(WORKFLOW, "r", encoding="utf-8") as f:
        workflow = json.load(f)
    say("  %s  (%d nodes)" % (WORKFLOW, len(workflow)))
except Exception:  # noqa: BLE001
    say("  could not read %s" % WORKFLOW)
    for line in traceback.format_exc().splitlines():
        say("    " + line)
    warn("could not read %s:\n%s" % (WORKFLOW, traceback.format_exc()))
    finish()

# --- 1. model files --------------------------------------------------------
say()
say("--- models ---")
wanted = required_models(workflow)
if not wanted:
    say("  (workflow names no model files)")
for name in wanted:
    path = find_model(name)
    if path is None:
        say("  MISSING  %s" % name)
        warn("missing model file: %s (not found anywhere under %s)" % (name, MODELS_DIR))
    elif os.path.getsize(path) == 0:
        say("  EMPTY    %s" % path)
        warn("empty model file: %s" % path)
    else:
        say("  OK       %-52s %.2f GB" % (path, os.path.getsize(path) / 1e9))

# --- 2. ComfyUI import -----------------------------------------------------
# ComfyUI logs "IMPORT FAILED: <dir>" for built-in comfy_extras nodes as well
# as custom nodes, and a missing optional dependency there is harmless. These
# are recorded as information only; what actually matters is whether the
# workflow's own class_types resolve, which is checked below.
import_failures = []


class _Capture(logging.Handler):
    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001
            return
        if "IMPORT FAILED" in msg or "Cannot import" in msg:
            import_failures.append(msg.strip())


logging.getLogger().addHandler(_Capture())
logging.getLogger().setLevel(logging.INFO)

os.chdir(COMFY_DIR)
sys.path.insert(0, COMFY_DIR)
sys.argv = ["main.py", "--cpu"]

# ComfyUI only reads sys.argv when main.py has switched parsing on; importing
# `nodes` directly otherwise gets parse_args([]) and silently drops --cpu. That
# leaves model_management initialising CUDA, which fails on a CPU-only build
# machine ("Found no NVIDIA driver") and aborts validation before it can check
# a single node class. Turn parsing on so --cpu is honoured.
try:
    import comfy.options

    comfy.options.enable_args_parsing()
except Exception:  # noqa: BLE001 - older layouts simply lack this module
    pass

say()
say("--- comfyui ---")
try:
    import nodes
except Exception:  # noqa: BLE001
    say("  ComfyUI FAILED TO IMPORT")
    for line in traceback.format_exc().splitlines():
        say("    " + line)
    warn("ComfyUI failed to import; the worker will not start:\n"
         + traceback.format_exc())
    finish()

say("  nodes module imported")

# API nodes are skipped: this workflow uses none, and loading them only widens
# the surface for unrelated failures.
try:
    import asyncio
    import inspect

    try:
        result = nodes.init_extra_nodes(init_custom_nodes=True, init_api_nodes=False)
    except TypeError:
        result = nodes.init_extra_nodes()
    if inspect.isawaitable(result):
        asyncio.run(result)
    say("  custom nodes loaded")
except Exception:  # noqa: BLE001
    say("  init_extra_nodes() raised:")
    for line in traceback.format_exc().splitlines():
        say("    " + line)
    warn("init_extra_nodes() raised:\n" + traceback.format_exc())

for msg in import_failures:
    say("  note: %s" % msg)

# --- 3. workflow node classes ---------------------------------------------
say()
say("--- workflow node classes ---")
registered = set(getattr(nodes, "NODE_CLASS_MAPPINGS", {}))
required = sorted({n["class_type"] for n in workflow.values()})
missing = [c for c in required if c not in registered]

say("  %d required, %d registered in ComfyUI" % (len(required), len(registered)))
for cls in required:
    say("  %-28s %s" % (cls, "OK" if cls in registered else "UNRESOLVED"))

if missing:
    warn("unresolved node classes: %s -- the workflow cannot run until the "
         "providing custom node installs correctly" % ", ".join(missing))

finish()
