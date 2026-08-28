"""Vision tool: ask a vision-capable model to describe an image.

Image paths are resolved INSIDE the agent's snapbox: the handler enters the
box with in-box(1) and pumps the file back over stdout as base64 between
sentinel lines, so stray wrapper noise on the stream cannot silently corrupt
the image. Path resolution anchors at the box home — the spawn's working
directory, which is where in-box always binds the home content. The pump
runs in a FRESH sibling environment: it has the same content as the agent's
environment, but not the same absolute path layout ($HOME proved unreliable
in --pipe spawns, and a sibling's view of absolute paths such as
<snapbox_root>/runs/<home>/... is a bare tmpfs — binds live in the owning
spawn's mount namespace). The agent-facing contract is therefore
deliberately narrow: a relative path resolved from the agent's home
directory. ~- and home-absolute spellings are still normalized onto the box
home as a courtesy, but the tool descriptions promise only the
relative-from-home form.

The bytes are downscaled via imagemagick on the harness side and sent to a
chat-completions vision model, returning either a thorough general description
or answers to specific questions. Intended for rigorous technical/mathematical
use: verifying rendered figures, reading plots, transcribing diagrams.

API robustness (anti-spam): transient failures (rate limits, 5xx, network
errors) are retried with backoff, bounded to a few attempts — the tool never
hammers the API, and its final error message tells the agent not to retry
immediately either. Permanent failures (4xx) are not retried at all.

Model/provider/plumbing are configurable via env:
  WHIM_VISION_MODEL     (default: qwen/qwen3-vl-235b-a22b-instruct)
  WHIM_VISION_PROVIDER  (optional provider order, fallbacks disabled)
  WHIM_IN_BOX           (in-box binary, default /usr/local/bin/in-box)
"""

import base64
import os
import random
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from pyt.core.llm.tools import tool, toolprop, tool_call
from pyt.core.llm.tools.images import (
    image_content_entry, bytes_content_entry, media_type_for_extension,
)

__all__ = ["describe_image", "look_at_image"]

API = os.environ.get("OPENROUTER_API_BASE", "https://openrouter.ai/api")
VISION_MODEL = os.environ.get("WHIM_VISION_MODEL",
                              "qwen/qwen3-vl-235b-a22b-instruct")
VISION_PROVIDER = os.environ.get("WHIM_VISION_PROVIDER")
IN_BOX = os.environ.get("WHIM_IN_BOX", "/usr/local/bin/in-env")
# Host constant of the snapbox installation; absolute paths under
# <root>/runs/<home>/ are rebased onto the box home by the pump.
SNAPBOX_ROOT = os.environ.get("WHIM_SNAPBOX_ROOT", "/snapbox")

DEFAULT_MAX_DIMENSION = 1568  # px; keeps base64 payloads reasonable
MAX_IMAGE_BYTES = 64 * 1024 * 1024  # sanity cap on bytes pumped out of the box
PUMP_TIMEOUT = 120    # seconds; box spawn + encode of a single file
REQUEST_TIMEOUT = 180  # seconds; one vision API call must not hang forever

# Anti-spam: bounded retries, only for failures that can plausibly recover.
# Permanent errors (400/401/402/403/404/422, ...) fail immediately.
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 2.0  # seconds; x4 per attempt (2, 8) with jitter
RETRYABLE_CODES = {408, 409, 425, 429, 500, 502, 503, 504}

# Sentinel lines bracket the base64 payload on the pump's stdout. '_' is not
# in the standard base64 alphabet, so these can never collide with payload.
_BEGIN = b"__WHIM_DESCRIBE_IMAGE_BEGIN__"
_END = b"__WHIM_DESCRIBE_IMAGE_END__"

# Runs INSIDE the agent's box: resolves the path the way the agent means it
# (~ and relative paths anchor at the box home), then pumps the bytes back as
# base64 between sentinel lines. Needs nothing but coreutils inside the box.
# Exit codes: 0 = payload on stdout, 3 = no such file, 4 = too large,
# 5 = base64 encode failed.
_PUMP_SCRIPT = r'''
f=$1
# Resolve the path the way the agent means it. The box home (what the agent
# sees as ~) is always the spawn's WORKING DIRECTORY with the home content
# bound there — proven live. $HOME is NOT trusted: in --pipe spawns it did
# not match the box home, and a sibling spawn's view of an absolute
# __ROOT__/runs/<home>/... path is a bare tmpfs (binds live in the owning
# box's mount namespace), so those are rebased onto the CWD too.
pick() {  # first existing candidate, else the first candidate (for errors)
    for c in "$@"; do [ -e "$c" ] && { printf '%s' "$c"; return; }; done
    printf '%s' "$1"
}
case $f in
    '~')   f=$(pick . "$HOME") ;;
    '~/'*) f=$(pick "./${f#??}" "$HOME/${f#??}") ;;
    __ROOT__/runs/*/*)
        f=$(pick "$f" "./${f#__ROOT__/runs/*/}") ;;
esac
if [ -d "$f" ]; then
    echo "describe_image: path is a directory, not an image file: $1 (resolved: $f)" >&2
    exit 3
fi
if [ ! -f "$f" ]; then
    echo "describe_image: no such file in box: $1 (resolved: $f)" >&2
    exit 3
fi
sz=$(stat -c %s -- "$f" 2>/dev/null); sz=${sz:-0}
if [ "$sz" -gt __MAX_BYTES__ ]; then
    echo "describe_image: file too large: $sz bytes (limit __MAX_BYTES__)" >&2
    exit 4
fi
echo '__WHIM_DESCRIBE_IMAGE_BEGIN__'
base64 -- "$f" || exit 5
echo '__WHIM_DESCRIBE_IMAGE_END__'
'''.replace("__MAX_BYTES__", str(MAX_IMAGE_BYTES)) \
    .replace("__ROOT__", SNAPBOX_ROOT)


class _PumpError(Exception):
    """The in-box read failed."""

class _PumpNotFound(_PumpError):
    """No such file inside the box."""

class _PumpTooLarge(_PumpError):
    """The file exceeds MAX_IMAGE_BYTES."""


def _extract_payload(stdout: bytes) -> bytes:
    """Pull the base64 payload out from between the sentinel lines."""
    start = stdout.find(_BEGIN)
    end = stdout.rfind(_END)
    if start == -1 or end == -1 or end < start + len(_BEGIN):
        raise _PumpError("garbled stream from the sandbox "
                         "(sentinel markers missing)")
    payload = re.sub(rb"\s+", b"", stdout[start + len(_BEGIN):end])
    try:
        return base64.b64decode(payload, validate=True)
    except Exception:
        raise _PumpError("garbled stream from the sandbox "
                         "(payload is not valid base64)")


def _pump_from_box(agent_name, path_str) -> bytes:
    """Read *path_str* out of the agent's snapbox via in-box(1)."""
    cmd = [IN_BOX]
    if agent_name:
        cmd += ["--as", str(agent_name)]
    cmd += ["--no-pty", "--quiet", "--",
            "bash", "-c", _PUMP_SCRIPT, "describe_image", path_str]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=PUMP_TIMEOUT)
    except FileNotFoundError:
        raise _PumpError(f"{IN_BOX} not found on the harness host")
    except subprocess.TimeoutExpired:
        raise _PumpError(f"timed out after {PUMP_TIMEOUT}s reading "
                         f"{path_str!r} from the sandbox")
    if proc.returncode == 3:
        detail = proc.stderr.decode(errors="replace").strip()
        raise _PumpNotFound(f"{path_str} — {detail}" if detail else path_str)
    if proc.returncode == 4:
        raise _PumpTooLarge(proc.stderr.decode(errors="replace").strip())
    if proc.returncode != 0:
        err = proc.stderr.decode(errors="replace").strip()
        raise _PumpError(f"in-box exited {proc.returncode}: {err[:300]}")
    return _extract_payload(proc.stdout)


def _failure(response):
    """None if the tool_call response is usable, else (message, code|None).

    OpenRouter reports errors either as a top-level "error" or (mid-stream /
    provider-side) inside choices[0].error; the code may be int or numeric
    string. Request-level failures (network/timeout) come back from
    tool_call as an error dict without a code -> treated as retryable.
    """
    err = response.get("error")
    if err is None:
        choices = response.get("choices") or []
        if choices and isinstance(choices[0], dict) and choices[0].get("error"):
            err = choices[0]["error"]
    if err is None:
        return None
    if isinstance(err, dict):
        code = err.get("code")
        if isinstance(code, str) and code.isdigit():
            code = int(code)
        if not isinstance(code, int):
            code = None
        return str(err.get("message", err)), code
    return str(err), None


def _failure_message(msg, code, attempts, retried):
    where = f" (HTTP {code})" if code else ""
    if retried:
        return (f"Error: vision call failed {attempts} times{where}: {msg}. "
                f"The vision service appears unavailable right now. Do NOT "
                f"retry describe_image immediately — continue with other "
                f"work and try again later if you still need it.")
    hint = ""
    if code == 402:
        hint = (" The API balance appears to be empty — the operator has to "
                "top it up, so do not retry.")
    elif code in (401, 403):
        hint = " This is an authorization problem; retrying will not help."
    return f"Error: vision call failed{where} (not retrying): {msg}.{hint}"


def _vision_call(messages):
    """Call the vision model, retrying transient failures with backoff.

    Returns (response, None) on success or (None, agent-facing error string).
    Bounded: at most MAX_ATTEMPTS attempts, only for retryable failures, so
    the tool can never spam the API no matter how often the agent calls it.
    """
    extra = {}
    if VISION_PROVIDER:
        extra["provider"] = {"order": [VISION_PROVIDER],
                             "allow_fallbacks": False}
    delay = RETRY_BASE_DELAY
    attempt = 0
    while True:
        attempt += 1
        response = tool_call(API, VISION_MODEL, messages, [],
                             request_timeout=REQUEST_TIMEOUT, **extra)
        failure = _failure(response)
        if failure is None:
            return response, None
        msg, code = failure
        retryable = code in RETRYABLE_CODES or code is None
        if not retryable or attempt >= MAX_ATTEMPTS:
            return None, _failure_message(msg, code, attempt,
                                          retried=retryable and attempt > 1)
        time.sleep(delay * (0.75 + 0.5 * random.random()))
        delay *= 4


GENERAL_PROMPT = (
    "Describe this image in careful, rigorous detail. The description will be "
    "used for mathematical and technical work, so precision matters more than "
    "brevity.\n"
    "- If it is a plot or figure: state the axes (labels, ranges, scales), "
    "what is plotted, and notable features (intercepts, extrema, asymptotes, "
    "symmetries, anomalies); estimate coordinates of salient points.\n"
    "- If it is a diagram: enumerate the elements and their labels, and give "
    "their exact spatial/logical relationships (what connects to what, "
    "intersections, angles, containment).\n"
    "- If it contains text or mathematics: transcribe it faithfully.\n"
    "- If it is a rendering (fractal, simulation frame, procedural art, ...): "
    "describe the structure, symmetries, color mapping, and any artifacts.\n"
    "Where something is ambiguous or illegible, say so explicitly rather than "
    "guessing."
)

QUESTION_PROMPT = (
    "Answer the following question(s) about this image with rigor and "
    "precision. This is for mathematical/technical work: be exact, give "
    "quantitative estimates where relevant, and say explicitly when something "
    "is ambiguous or illegible rather than guessing.\n\n"
    "Question(s):\n{question}"
)

def _normalize_box_path(path_str):
    """Rewrite ~ and box-home-absolute paths to box-relative form.

    The pump runs with its CWD set to the agent's box home, so a plain
    relative path means "inside the box home". A leading-~ path and a
    /snapbox/runs/<home>/... path are the same thing spelled differently;
    normalize them here because the in-box/systemd-run argument chain mangles
    a literal leading '~' (observed live: the pump resolved '~/x' as '.',
    firing its '~'-only branch). A plain relative path is proven to survive
    the chain intact.
    """
    if path_str == "~":
        return "."
    if path_str.startswith("~/"):
        return "./" + path_str[2:]
    prefix = SNAPBOX_ROOT.rstrip("/") + "/runs/"
    if path_str.startswith(prefix):
        parts = path_str.split("/")
        # parts == ['', 'snapbox', 'runs', '<home>', <rest...>]
        if len(parts) >= 5:
            rest = "/".join(parts[4:])
            return ("./" + rest) if rest else "."
    return path_str


def _load_image_entry(session, path_str, maxdim):
    """Read + downscale an image. Returns
    (content_entry, None) or (None, agent-facing error string)."""

    # Sandboxed: pull the bytes out of the agent's own box, so paths
    # mean exactly what they mean in the agent's command shell.
    path_str = _normalize_box_path(path_str.strip())
    media_type = media_type_for_extension(Path(path_str).suffix)
    try:
        raw = _pump_from_box(session.get("snapbox_name"),
                             path_str)
    except _PumpNotFound as e:
        return None, (f"Error: no image file inside your sandbox: {e}. "
                      f"Paths are resolved relative to your sandbox "
                      f"home — absolute paths do not work there the "
                      f"way they do in your shell. Check with "
                      f"run_command that the file exists.")
    except _PumpError as e:
        return None, f"Error: could not read image from your sandbox: {e}"
    if not raw:
        return None, f"Error: image file at {path_str!r} is empty"

    try:
        entry = bytes_content_entry(
            raw, imagemagick_args=["-resize", f"{maxdim}x{maxdim}>"])
    except Exception:
        # imagemagick unavailable/failed — send the raw bytes
        if media_type is None:
            return None, (f"Error: unsupported image extension "
                          f"{Path(path_str).suffix!r} and imagemagick "
                          f"could not convert it")
        try:
            entry = bytes_content_entry(raw, media_type)
        except Exception as e:
            return None, f"Error: could not encode {path_str}: {e}"

    return entry, None


@tool
class describe_image:
    """Get a detailed description of an image from a vision-capable model.

    Use whenever you have rendered or saved an image (plot, diagram, fractal,
    simulation frame, ...) and need to know what it actually contains — e.g.
    to verify a figure matches your intent, or to extract precise information
    from it for mathematical work. Omit `question` for a thorough general
    description, or provide it to ask something specific.

    The path is resolved inside YOUR sandbox relative to your home
    directory: pass a plain relative path from home (e.g. plots/fig1.png).
    Do NOT pass an absolute path — the image is read in a fresh environment
    that has the same files as yours but not the same absolute layout, so
    an absolute path does not mean there what it means in your shell.

    Transient API failures are already retried internally with backoff; if
    this tool returns an error, do NOT call it again right away — continue
    with other work and try again later."""

    path: str = toolprop(
        desc="Path to the image file (png, jpg, gif, webp), relative to "
             "your sandbox home (e.g. plots/fig1.png). Absolute paths are "
             "unreliable here — use a relative path from home.")

    question: Optional[str] = toolprop(default=None,
        desc="Specific question(s) about the image. Omit for a detailed "
             "general description.")
    max_dimension: Optional[int] = toolprop(default=None,
        desc=f"Downscale so the longest side is at most this many pixels "
             f"before sending (default {DEFAULT_MAX_DIMENSION}).")

    # A single vision API attempt can take well over 10s (big VL model), and
    # this tool's result is usually exactly what the agent is waiting for, so
    # let run_with_timeout wait synchronously through one attempt instead of
    # detaching immediately and surfacing the answer only on a later step.
    sync_timeout = 190

    def handler(agent, session, args):
        maxdim = int(args.get("max_dimension") or DEFAULT_MAX_DIMENSION)
        entry, error = _load_image_entry(session, str(args.path), maxdim)
        if error:
            return error

        question = args.get("question")
        text = (QUESTION_PROMPT.format(question=question)
                if question else GENERAL_PROMPT)

        response, error = _vision_call(
            [{"role": "user",
              "content": [entry, {"type": "text", "text": text}]}])
        if error:
            return error

        choices = response.get("choices") or []
        content = (choices[0].get("message", {}).get("content")
                   if choices else None)
        if not content:
            return f"Error: vision model returned no content: {str(response)[:500]}"
        return content


@tool
class look_at_image:
    """Put an image directly into your own context so YOU can see it.

    Use whenever you have rendered or saved an image (plot, diagram, fractal,
    simulation frame, ...) and need to know what it actually contains — e.g.
    to verify a figure matches your intent, or to extract precise information
    from it for mathematical work. The image shows up as a user message right
    after this tool round; from then on it is simply part of your context and
    you can reason about it yourself.

    The path is resolved inside YOUR sandbox relative to your home
    directory: pass a plain relative path from home (e.g. plots/fig1.png).
    Do NOT pass an absolute path — the image is read in a fresh environment
    that has the same files as yours but not the same absolute layout, so
    an absolute path does not mean there what it means in your shell."""

    path: str = toolprop(
        desc="Path to the image file (png, jpg, gif, webp), relative to "
             "your sandbox home (e.g. plots/fig1.png). Absolute paths are "
             "unreliable here — use a relative path from home.")
    max_dimension: Optional[int] = toolprop(default=None,
        desc=f"Downscale so the longest side is at most this many pixels "
             f"first (default {DEFAULT_MAX_DIMENSION}).")

    # Same box pump as describe_image (but no downstream API call), so the
    # same generous synchronous window applies.
    sync_timeout = 190

    def handler(agent, session, args):
        maxdim = int(args.get("max_dimension") or DEFAULT_MAX_DIMENSION)
        path_str = str(args.path).strip()
        entry, error = _load_image_entry(session, path_str, maxdim)
        if error:
            return error

        # Deferred insertion: the worker appends this as a user message only
        # after the whole tool-result block, so strict assistant→tool
        # ordering holds no matter how many calls share the round.
        caption = (f"[automated message] image from look_at_image: "
                   f"{path_str}")
        pending = session.setdefault("pending_images", [])
        pending.append({
            "role": "user",
            "content": [entry, {"type": "text", "text": caption}],
        })
        return (f"Image {path_str!r} placed into context — it appears as a "
                f"user message right after this tool round.")
