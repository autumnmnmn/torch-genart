import os
import sys
import errno
import shutil
import subprocess
import time
import atexit
import threading
import uuid

from pyt.core.terminal.ansi import codes as ac

CLEAR = ac.clear_screen + ac.move_to(1, 1)

_BIDIRECTIONAL_READER = r'''import os
import sys
import shutil
import select
import threading
import termios
import tty
import unicodedata

DISPLAY = __DISPLAY__
INPUT = __INPUT__
CLEAR = __CLEAR__

_buf = ""
_cur = 0
_buf_lock = threading.Lock()
_print_lock = threading.Lock()

# Wrap-aware repaint state. The input block ("> " + buf) can occupy SEVERAL
# terminal rows once it wraps. We track how many rows the last paint used
# and how far below the block's first row the cursor was left, so the next
# paint can return to the block start and clear the whole block before
# rewriting. (The session-26 bug: repaints assumed a single row, so a
# wrapped line was duplicated on every keypress.)
_paint = {"rows": 1, "cur_row": 0, "width": 0, "height": 0}
_last_frame = ""   # last transcript frame, for repainting after a resize

def _get_buf():
    with _buf_lock:
        return _buf

def _get_cur():
    with _buf_lock:
        return _cur

def _set(buf, cur):
    global _buf, _cur
    with _buf_lock:
        _buf = buf
        _cur = cur

def _read_timeout(fd, timeout):
    r, _, _ = select.select([fd], [], [], timeout)
    if not r:
        return None
    return os.read(fd, 1)

def _move(cur, delta, length):
    cur += delta
    if cur < 0:
        return 0
    if cur > length:
        return length
    return cur

def _prev_word(buf, cur):
    i = cur
    while i > 0 and buf[i-1].isspace():
        i -= 1
    while i > 0 and not buf[i-1].isspace():
        i -= 1
    return i

def _next_word(buf, cur):
    i = cur
    while i < len(buf) and buf[i].isspace():
        i += 1
    while i < len(buf) and not buf[i].isspace():
        i += 1
    return i

def _apply_escape(buf, cur, seq):
    if len(seq) < 2:
        return buf, cur
    kind = seq[1:2]
    if kind == b"[":
        body = seq[2:]
        if not body:
            return buf, cur
        final = body[-1:]
        params = body[:-1].decode("ascii", "ignore")
        if final == b"D":
            if ";5" in params or ";3" in params:
                return buf, _prev_word(buf, cur)
            return buf, _move(cur, -1, len(buf))
        if final == b"C":
            if ";5" in params or ";3" in params:
                return buf, _next_word(buf, cur)
            return buf, _move(cur, 1, len(buf))
        if final == b"H":
            return buf, 0
        if final == b"F":
            return buf, len(buf)
        if final == b"~":
            if params == "3" and cur < len(buf):
                return buf[:cur] + buf[cur+1:], cur
            if params in ("1", "7"):
                return buf, 0
            if params in ("4", "8"):
                return buf, len(buf)
        return buf, cur
    if kind == b"O":
        body = seq[2:]
        final = body[-1:] if body else b""
        if final == b"D":
            return buf, _move(cur, -1, len(buf))
        if final == b"C":
            return buf, _move(cur, 1, len(buf))
        if final == b"H":
            return buf, 0
        if final == b"F":
            return buf, len(buf)
        return buf, cur
    if kind == b"b":
        return buf, _prev_word(buf, cur)
    if kind == b"f":
        return buf, _next_word(buf, cur)
    return buf, cur

def _cellw(text):
    """Display cell width (wide chars count 2, combining marks 0)."""
    w = 0
    for ch in text:
        if unicodedata.combining(ch):
            continue
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w

def _term_size():
    # ioctl the real pty. shutil.get_terminal_size() prefers $COLUMNS/$LINES,
    # which the reader inherits from the worker's env and which go stale on
    # the first resize -- with a too-large value the wrap math below thinks
    # the input fits on one row and never returns to the block start, so
    # every keystroke reprinted the whole block (autumn, 15.08).
    try:
        sz = os.get_terminal_size(sys.__stdout__.fileno())
        return max(4, sz.columns), max(2, sz.lines)
    except Exception:
        pass
    try:
        sz = shutil.get_terminal_size()
        return max(4, sz.columns), max(2, sz.lines)
    except Exception:
        return 80, 24

def _input_geometry(buf, cur, width):
    """(rows, cursor_row, cursor_col) of the painted input block.

    Rows count wrapped terminal rows of "> " + buf. A block whose length is
    an exact multiple of the width still occupies ceil-ish rows with the
    terminal in wrap-pending; the cursor target is clamped onto the last
    real row in that case (it corrects itself on the next keystroke).
    """
    plen = 2 + _cellw(buf)
    rows = max(1, (max(plen, 1) - 1) // width + 1)
    ccells = 2 + _cellw(buf[:cur])
    tgt_row, tgt_col = divmod(ccells, width)
    if tgt_row >= rows:
        tgt_row, tgt_col = rows - 1, width - 1
    return rows, tgt_row, tgt_col

def _paint_input():
    buf = _get_buf()
    cur = _get_cur()
    width, height = _term_size()
    rows, tgt_row, tgt_col = _input_geometry(buf, cur, width)
    # Cursor is _paint["cur_row"] rows below the block start (only our own
    # writes move it; echo is off, and _maybe_resize handles reflow).
    up = _paint["cur_row"]
    with _print_lock:
        parts = []
        if up:
            parts.append("\x1b[%dA" % up)
        parts.append("\r\x1b[J")          # block start; clear to screen end
        parts.append("> " + buf)
        back = (rows - 1) - tgt_row
        if back:
            parts.append("\x1b[%dA" % back)
        parts.append("\r")
        if tgt_col:
            parts.append("\x1b[%dC" % tgt_col)
        sys.stdout.write("".join(parts))
        sys.stdout.flush()
    _paint["rows"] = rows
    _paint["cur_row"] = tgt_row
    _paint["width"] = width
    _paint["height"] = height

def _fresh_prompt():
    """Move to just past the block's last row, newline, paint '> '."""
    down = (_paint["rows"] - 1) - _paint["cur_row"]
    seq = ""
    if down > 0:
        seq += "\x1b[%dB" % down
    seq += "\r\n> "
    _paint["rows"] = 1
    _paint["cur_row"] = 0
    return seq

def _visible_lines(frame, width, budget):
    """Wrap-aware tail of the transcript that fits in `budget` screen rows."""
    if budget <= 0:
        return []
    lines = frame.split("\n")
    keep = []
    used = 0
    for line in reversed(lines):
        cost = max(1, (max(_cellw(line), 1) - 1) // width + 1)
        if used + cost > budget and keep:
            break
        keep.append(line)
        used += cost
        if used >= budget:
            break
    keep.reverse()
    return keep

def input_loop():
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setraw(fd)
    try:
        with open(INPUT, "w") as out:
            while True:
                try:
                    ch = os.read(fd, 1)
                except OSError:
                    break
                if not ch:
                    break
                _maybe_resize()
                buf = _get_buf()
                cur = _get_cur()
                if ch in (b"\r", b"\n"):
                    with _print_lock:
                        sys.stdout.write(_fresh_prompt())
                        sys.stdout.flush()
                    _set("", 0)
                    try:
                        out.write(buf + "\n")
                        out.flush()
                    except Exception:
                        break
                elif ch == b"\x1b":
                    seq = b"\x1b"
                    nxt = _read_timeout(fd, 0.05)
                    if nxt is None:
                        continue
                    seq += nxt
                    if nxt in (b"[", b"O"):
                        while True:
                            b = _read_timeout(fd, 0.05)
                            if b is None:
                                break
                            seq += b
                            if 0x40 <= b[0] <= 0x7E:
                                break
                    nb, nc = _apply_escape(buf, cur, seq)
                    if nb != buf or nc != cur:
                        _set(nb, nc)
                        _paint_input()
                elif ch in (b"\x7f", b"\x08"):
                    if cur > 0:
                        _set(buf[:cur-1] + buf[cur:], cur-1)
                        _paint_input()
                elif ch == b"\x03":
                    with _print_lock:
                        sys.stdout.write(_fresh_prompt())
                        sys.stdout.flush()
                    _set("", 0)
                elif ch == b"\x04":
                    if not buf:
                        break
                    if cur < len(buf):
                        _set(buf[:cur] + buf[cur+1:], cur)
                        _paint_input()
                else:
                    pending = ch
                    text = ""
                    while True:
                        try:
                            text = pending.decode("utf-8")
                            break
                        except UnicodeDecodeError:
                            nxt = os.read(fd, 1)
                            if not nxt:
                                break
                            pending += nxt
                    if text:
                        _set(buf[:cur] + text + buf[cur:], cur + len(text))
                        _paint_input()
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except Exception:
            pass

def _full_repaint(frame):
    buf = _get_buf()
    cur = _get_cur()
    width, height = _term_size()
    rows, tgt_row, tgt_col = _input_geometry(buf, cur, width)
    with _print_lock:
        parts = [CLEAR]
        lines = _visible_lines(frame, width, height - rows)
        if lines:
            parts.append("\r\n".join(lines))
            parts.append("\r\n")
        parts.append("> " + buf)
        back = (rows - 1) - tgt_row
        if back:
            parts.append("\x1b[%dA" % back)
        parts.append("\r")
        if tgt_col:
            parts.append("\x1b[%dC" % tgt_col)
        sys.stdout.write("".join(parts))
        sys.stdout.flush()
        _paint["rows"] = rows
        _paint["cur_row"] = tgt_row
        _paint["width"] = width
        _paint["height"] = height

def _maybe_resize():
    # A resize reflows the screen, invalidating the incremental paint state;
    # the next transcript frame could be minutes away, so heal right now.
    if _term_size() != (_paint["width"], _paint["height"]):
        _full_repaint(_last_frame)

def display_loop():
    global _last_frame
    while True:
        with open(DISPLAY, "r") as f:
            frame = f.read()
        _last_frame = frame
        _full_repaint(frame)

__REAPER__

if __name__ == "__main__":
    threading.Thread(target=input_loop, daemon=True).start()
    display_loop()
'''



def _reaper_snippet(worker_pid, fifo_paths):
    # Reader-script fragment: self-destruct (and remove the orphaned fifos)
    # when the worker process is gone, so a worker killed without cleanup
    # doesn't leave a ghost window showing a dead session's last frame.
    return f'''
import time as _time

def _reaper():
    while True:
        _time.sleep(2)
        try:
            os.kill({worker_pid}, 0)
        except OSError:
            for _p in {fifo_paths!r}:
                try:
                    os.unlink(_p)
                except OSError:
                    pass
            os._exit(0)

threading.Thread(target=_reaper, daemon=True).start()
'''


class MonitorWindow:
    """A frame stream rendered in its own alacritty window.

    Spawns lazily on first ``write`` and degrades to a headless no-op (dropping
    frames) when alacritty or a display is unavailable, so headless imports and
    dead displays never crash or wedge the caller.

    The window is optionally bidirectional: pass ``on_input`` and every line
    typed into the window is forwarded back to this process and handed to
    ``on_input(line)`` on a daemon thread.  Without ``on_input`` the window is
    display-only, exactly as before.
    """

    def __init__(self, max_buffered_frames=0, warn=True, on_input=None, title=None):
        self.fifo_path = None
        self.input_fifo_path = None
        self.proc = None
        self._ready = False
        self._headless = None              # None = undecided, else bool
        self._warned = False
        self._max_buffered = max_buffered_frames
        self._buffer = []
        self._on_input = on_input
        self.title = title
        self._input_thread = None
        self._closing = False
        atexit.register(self._cleanup)

        if shutil.which("alacritty") is None:
            self._go_headless(warn)

    # -- lifecycle -----------------------------------------------------

    def _go_headless(self, warn=True):
        self._headless = True
        if warn and not self._warned:
            self._warned = True
            print("MonitorWindow: alacritty not found -- running headless "
                  "(frames dropped, no window spawned).", file=sys.stderr)

    def _make_fifo(self):
        self.fifo_path = f"/tmp/monitor_{uuid.uuid4().hex}.fifo"
        if os.path.exists(self.fifo_path):
            os.remove(self.fifo_path)
        os.mkfifo(self.fifo_path)

        if self._on_input is not None:
            self.input_fifo_path = f"/tmp/monitor_in_{uuid.uuid4().hex}.fifo"
            if os.path.exists(self.input_fifo_path):
                os.remove(self.input_fifo_path)
            os.mkfifo(self.input_fifo_path)

    def _reader_script(self):
        display = self.fifo_path
        if self._on_input is None:
            return f"""
import os
import threading
{_reaper_snippet(os.getpid(), [display])}
path = {display!r}
while True:
    with open(path, "r") as f:
        frame = f.read()
    print({CLEAR!r}, end="", flush=True)
    print(frame, end="", flush=True)
"""
        # The bidirectional window owns its own raw-mode line editor (the
        # "hiya" bug: a mid-line transcript redraw used to erase the echo of
        # half-typed text). We redraw the in-progress line ourselves and parse
        # arrow/ctrl-arrow/home/end/delete escapes so cursor keys edit the
        # line instead of leaking raw escape bytes into it.
        return (_BIDIRECTIONAL_READER
                .replace("__DISPLAY__", repr(display))
                .replace("__INPUT__", repr(self.input_fifo_path))
                .replace("__CLEAR__", repr(CLEAR))
                .replace("__REAPER__", _reaper_snippet(
                    os.getpid(), [display, self.input_fifo_path])))

    def _spawn(self):
        """Start the alacritty reader if we haven't already."""
        if self._ready or self._headless:
            return
        if shutil.which("alacritty") is None:
            self._go_headless()
            return

        self._make_fifo()
        reader_script = self._reader_script()

        try:
            cmd = ["alacritty"]
            if self.title:
                cmd += ["--title", self.title]
            cmd += ["-e", "python3", "-c", reader_script]
            self.proc = subprocess.Popen(
                cmd,
                preexec_fn=os.setsid,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)   # let the window come up before first frame
            if self.proc.poll() is not None:
                # alacritty exited immediately (no display server)
                self.proc = None
                self._go_headless(warn=False)
                return
            self._ready = True
            if self._on_input is not None:
                self._start_input_reader()
        except Exception as e:
            self.proc = None
            self._go_headless(warn=False)
            print(f"MonitorWindow: could not spawn alacritty ({e}); "
                  "continuing headless.", file=sys.stderr)

    def _start_input_reader(self):
        if self._input_thread is not None:
            return
        self._input_thread = threading.Thread(
            target=self._read_input_loop, daemon=True, name="monitor-input")
        self._input_thread.start()

    def _read_input_loop(self):
        """Read typed lines from the window and forward them to ``on_input``."""
        try:
            with open(self.input_fifo_path, "r") as f:
                for line in f:
                    if self._closing:
                        break
                    line = line.rstrip("\n")
                    try:
                        self._on_input(line)
                    except Exception:
                        pass
        except Exception:
            pass

    # -- interface -----------------------------------------------------

    def _open_fifo_nonblocking(self):
        """Open the fifo for writing without blocking on a missing reader."""
        if self.fifo_path is None:
            return None
        try:
            return os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno in (errno.ENXIO, errno.ENOENT):
                return None          # no reader (window died)
            raise

    def write(self, content: str):
        if self._headless is None:
            # alacritty existed at init; re-check in case it vanished
            if shutil.which("alacritty") is None:
                self._go_headless(warn=False)
        if self._headless:
            if self._max_buffered:
                self._buffer.append(content)
                if len(self._buffer) > self._max_buffered:
                    self._buffer.pop(0)
            return

        self._spawn()
        if not self._ready:
            return

        fd = self._open_fifo_nonblocking()
        if fd is None:
            if self.proc is not None and self.proc.poll() is None:
                # Window alive but the reader was between fifo reads, so
                # the nonblocking open failed transiently. Drop just this
                # frame; the next write re-renders and the display heals.
                # (Killing the window here used to permanently silence the
                # channel mid-session -- after one unlucky race, nothing
                # posted to the window ever again.)
                return
            # reader vanished -- drop to headless rather than risk wedging
            self._go_headless(warn=False)
            if self.proc is not None:
                try:
                    os.killpg(os.getpgid(self.proc.pid), 15)
                except Exception:
                    pass
                self.proc = None
            return

        try:
            view = memoryview(content.encode("utf-8", errors="replace"))
            while view:
                try:
                    n = os.write(fd, view)
                except BlockingIOError:
                    break            # reader busy; drop rest of frame
                view = view[n:]
        finally:
            os.close(fd)

    def _cleanup(self):
        self._closing = True
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), 15)
            except Exception:
                pass
        if self._input_thread is not None:
            self._input_thread.join(timeout=1.0)
            self._input_thread = None
        if self.fifo_path and os.path.exists(self.fifo_path):
            try:
                os.remove(self.fifo_path)
            except Exception:
                pass
        if self.input_fifo_path and os.path.exists(self.input_fifo_path):
            try:
                os.remove(self.input_fifo_path)
            except Exception:
                pass
