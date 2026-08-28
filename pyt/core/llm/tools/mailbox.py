"""Operator <-> agent "mail" channel for the whim worker.

The headless worker has no interactive terminal of its own, so the operator
talks to the running agent through a dedicated two-way monitor window: a
scrolling mail log. Capability requests and notices are posted to the
window; the operator answers by typing into it — ordinary lines become
``[autumn]`` user messages for the agent, and ``approve <id>`` /
``deny <id> [note]`` lines resolve pending capability requests. Requests stay
pending until answered — there is no approval expiry by default
(WHIM_APPROVAL_TIMEOUT can set one) — so the operator can answer long after
the agent has moved on to other work, and the waiting command runs
automatically when approval lands.

All state is in-process. Operator messages wait in a small locked queue and
pending requests live in a dict keyed by request id, signalled with
threading events. The window shows a bounded transcript that is re-rendered
on every update (MonitorWindow is a frame stream — a plain ``write``
replaces the whole frame), so a new request never erases an unanswered one
and every typed line gets a visible confirmation. Lines typed into the
window reach :func:`handle_operator_line` through MonitorWindow's on_input
callback; there is no filesystem protocol and nothing to poll.
"""

import os
import time
import itertools
import threading
from collections import deque

from typing import Optional

from pyt.core.llm.tools import tool, toolprop
from pyt.core.terminal.monitor import MonitorWindow

# Default operator response window. None means a capability request stays
# pending until the operator answers, however long that takes — the operator
# is not always at the keyboard, and the agent keeps working meanwhile (the
# blocking handler is detached by run_with_timeout). WHIM_APPROVAL_TIMEOUT
# can set a finite window in seconds.
APPROVAL_TIMEOUT_SECONDS = None
TRANSCRIPT_MAX_ENTRIES = 100      # bounded mail log rendered in the window

# Decision lines are exactly these two verbs (case-insensitive) followed by a
# request id: "approve <id> [note]" / "deny <id> [note]". Anything else typed
# into the window is ordinary operator mail for the agent.
_DECISION_WORDS = ("approve", "deny")

# Capability request ids are short, typist-friendly sequence numbers assigned
# in process order: "1", "2", "3", ... (never reused within a process). The
# mail window prints the id next to each request, so the operator only has to
# type e.g. "approve 1".
_id_counter = itertools.count(1)

# In-memory operator -> agent message queue.
_inbox = []
_inbox_lock = threading.Lock()

# In-memory capability requests awaiting an operator decision.
_pending = {}
_pending_lock = threading.Lock()

# Bounded mail log; the window always shows the whole transcript.
_transcript = deque(maxlen=TRANSCRIPT_MAX_ENTRIES)
_transcript_lock = threading.Lock()

_mail_monitor = None
_mail_monitor_lock = threading.Lock()


class _CapabilityRequest:
    def __init__(self, request_id, command, capabilities):
        self.request_id = request_id
        self.command = command
        self.capabilities = list(capabilities)
        self.submitted = time.time()
        self.event = threading.Event()
        self.decision = None
        self.note = ""


# ── operator -> agent messages ─────────────────────────────────────

def _post_message(text):
    with _inbox_lock:
        _inbox.append(text)


def drain_inbox():
    """Return (and clear) pending operator messages as a list of strings."""
    with _inbox_lock:
        messages = list(_inbox)
        _inbox.clear()
    return messages


# ── the window transcript ──────────────────────────────────────────

def _post(text):
    """Append *text* to the mail transcript and re-render the window.

    Never raises; headless this just accumulates in the bounded transcript.
    """
    try:
        with _transcript_lock:
            _transcript.append(text)
            frame = "\n".join(_transcript)
    except Exception:
        return
    try:
        get_mail_monitor().write(frame)
    except Exception:
        pass


def _mail_banner():
    return "\n".join([
        "=" * 64,
        "whim mail",
        "Type a message and press enter to send it to the agent.",
        "Answer capability requests with: approve <id>  or  deny <id>",
        "(ids are short numbers, e.g. 1, 2, 3 — shown above each request)",
        "=" * 64,
    ])


def _request_text_for_window(request_id, command, capabilities,
                             justification=None):
    timeout = approval_timeout()
    wait_note = ("This request stays pending until you answer it."
                 if timeout is None else
                 f"This request expires in {timeout:.0f}s if you don't answer.")
    return "\n".join([
        "=" * 64,
        f"CAPABILITY REQUEST {request_id}",
        f"Submitted: {time.strftime('%d.%m.%Y t%H.%M.%S')}",
        f"Capabilities: {', '.join(capabilities)}",
        "",
        "Command:",
        command,
        "",
        "Agent's justification:",
        justification if justification else "(none given)",
        "",
        wait_note,
        "Reply in this window with:",
        f"  approve {request_id}",
        f"  deny {request_id}",
        "=" * 64,
    ])


def get_mail_monitor():
    """Return (and lazily construct) the process-wide mail monitor window."""
    global _mail_monitor
    with _mail_monitor_lock:
        if _mail_monitor is None:
            _mail_monitor = MonitorWindow(title="whim mail",
                                          on_input=handle_operator_line)
        return _mail_monitor


def launch_mail_monitor():
    """Launch the mail window and show the operator-facing banner.

    Safe to call headless: the window degrades to a no-op and typed messages
    simply have nowhere to arrive (there is no filesystem fallback).
    """
    _post(_mail_banner())
    return get_mail_monitor()


def close_mail_monitor():
    """Clean up the mail window, if one was ever created."""
    global _mail_monitor
    with _mail_monitor_lock:
        if _mail_monitor is not None:
            try:
                _mail_monitor._cleanup()
            except Exception:
                pass
            _mail_monitor = None


# ── typed-line routing (the monitor's 2-way input callback) ────────

def _decide(request_id, decision, note=""):
    """Resolve a pending request. Returns True if the id was still pending."""
    with _pending_lock:
        req = _pending.get(request_id)
    if req is None:
        return False
    req.decision = decision
    req.note = note
    req.event.set()
    return True


def handle_operator_line(line):
    """Route one line typed into the mail window.

    ``approve <id> [note]`` / ``deny <id> [note]`` resolve a pending
    capability request; any other non-empty line is queued as an operator
    message for the agent. Every line gets a visible confirmation in the
    transcript, so the operator can tell their input landed.
    """
    line = (line or "").strip()
    if not line:
        return
    parts = line.split()
    first = parts[0].lower()
    if first in _DECISION_WORDS:
        decision = first
        if len(parts) < 2:
            _post(f"> {line}\ncouldn't parse that — answer requests with: "
                  f"approve <id> / deny <id> [note]")
            return
        request_id = parts[1]
        note = " ".join(parts[2:])
        if _decide(request_id, decision, note):
            verdict = "approved" if decision == "approve" else "denied"
            _post(f"> {line}\nrequest {request_id} {verdict}"
                  + (f" ({note})" if note else ""))
        else:
            _post(f"> {line}\nno pending request {request_id} "
                  f"(unknown or expired id)")
        return
    _post_message(line)
    _post(f"> {line}\nmessage sent to the agent")


# ── capability requests / decisions ────────────────────────────────

def submit_capability_request(command, capabilities, justification=None):
    """Show a capability request in the mail window and return its id.

    The request is registered in-process so :func:`poll_approval` can wait
    for the operator to type ``approve <id>`` / ``deny <id>`` in the window.
    *justification* is the agent's due-diligence brief — what the command is
    for, which concerns are relevant to it, and why the agent is confident it
    should be approved — shown verbatim so the operator can judge the request
    on its merits.
    """
    with _pending_lock:
        while True:
            request_id = str(next(_id_counter))
            if request_id not in _pending:
                break
        req = _CapabilityRequest(request_id, command, capabilities)
        _pending[request_id] = req
    _post(_request_text_for_window(request_id, command, capabilities,
                                   justification))
    return request_id


def approval_timeout():
    """How long a capability request waits for the operator, in seconds.

    ``None`` — the default — means the request stays pending until it is
    answered, however long that takes: the operator is not always at the
    keyboard, and the agent keeps working on other things while the detached
    handler waits. Set WHIM_APPROVAL_TIMEOUT to a positive number of seconds
    to bound the wait; unset/empty/invalid/non-positive values and "none"
    all mean "wait indefinitely".
    """
    raw = (os.environ.get("WHIM_APPROVAL_TIMEOUT") or "").strip().lower()
    if not raw or raw in ("none", "inf", "infinite", "forever"):
        return APPROVAL_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return APPROVAL_TIMEOUT_SECONDS
    return value if value > 0 else APPROVAL_TIMEOUT_SECONDS


def poll_approval(request_id, timeout):
    """Wait for a decision on *request_id*.

    Returns ``(decision, note)`` where *decision* is ``"approve"`` or
    ``"deny"``. A *timeout* of ``None`` waits indefinitely — there is no
    expiry path, the request simply stays pending until answered. With a
    finite timeout, ``(None, "")`` is returned when the window elapses; the
    request is then popped, so a late operator answer gets an "unknown or
    expired id" note rather than deciding a ghost.
    """
    with _pending_lock:
        req = _pending.get(request_id)
    if req is None:
        return (None, "")

    decided = req.event.wait() if timeout is None else req.event.wait(timeout)
    if not decided:
        with _pending_lock:
            _pending.pop(request_id, None)
        _post(f"request {request_id} expired without a decision")
        return (None, "")

    with _pending_lock:
        _pending.pop(request_id, None)
    return (req.decision, req.note)

# ── agent -> operator mail ─────────────────────────────────────────

@tool
class send_operator_message:
    """Send a message straight to autumn's mail window.

    Use this when you want to make sure autumn sees something (a
    question, a heads-up, a request that needs their eyes) without it being
    buried in your working notes. The message is posted verbatim to the same
    window where autumn types their replies.
    """
    message: str = toolprop(desc="The message to show autumn.")

    def handler(agent, session, args):
        text = (args.get("message") or "").strip()
        if not text:
            return "No message text was given; nothing was sent."
        try:
            _post("AGENT: " + text)
        except Exception as e:
            return f"Could not send message: {e}"
        return "Message sent to autumn's mail window."


@tool
class wait_for_operator:
    """Pause the session and hibernate until autumn replies in the mail window.

    Use this when you've asked autumn something (typically via
    send_operator_message) and further work depends on the answer: rather
    than ending the session or polling with expensive model turns, this parks
    the session — no API calls are made while waiting. As soon as autumn
    types anything into the mail window, their message arrives as a normal
    "[autumn]" user message and the session resumes by itself. Like
    capability requests, there is no expiry by default; set
    `timeout_seconds` if you'd rather give up and carry on after a while.
    """
    note: Optional[str] = toolprop(default=None,
        desc="Optional short message posted to the mail window as the wait "
             "begins, so autumn can see at a glance what you're waiting on.")
    timeout_seconds: Optional[float] = toolprop(default=None,
        desc="Give up waiting after this many seconds and continue without "
             "an answer. Default: wait indefinitely.")

    def handler(agent, session, args):
        # Autumn talks to the TOP-LEVEL agent; set the flag on the root
        # session, which is what the run loop watches.
        root = session
        while True:
            parent = root.get("parent")
            if parent is None or parent is root:
                break
            root = parent
        note = (args.get("note") or "").strip()
        if note:
            try:
                _post("AGENT (waiting for a reply): " + note)
            except Exception:
                pass
        timeout = args.get("timeout_seconds")
        root["waiting_for_operator"] = True
        root["operator_wait_deadline"] = (time.time() + float(timeout)
                                         if timeout else None)
        return ("Now waiting for autumn. No API calls will be made until a "
                "reply arrives" +
                (f" or {float(timeout):.0f}s elapse." if timeout else "."))
