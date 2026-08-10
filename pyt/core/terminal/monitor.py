import os
import sys
import errno
import shutil
import subprocess
import time
import atexit
import uuid

from pyt.core.terminal.ansi import codes as ac

CLEAR = ac.clear_screen + ac.move_to(1, 1)

class MonitorWindow:
    """A frame stream rendered in its own alacritty window.

    Spawns lazily on first ``write`` and degrades to a headless no-op (dropping
    frames) when alacritty or a display is unavailable, so headless imports and
    dead displays never crash or wedge the caller.
    """

    def __init__(self, max_buffered_frames=0, warn=True):
        self.fifo_path = None
        self.proc = None
        self._ready = False
        self._headless = None              # None = undecided, else bool
        self._warned = False
        self._max_buffered = max_buffered_frames
        self._buffer = []
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

    def _spawn(self):
        """Start the alacritty reader if we haven't already."""
        if self._ready or self._headless:
            return
        if shutil.which("alacritty") is None:
            self._go_headless()
            return

        self.fifo_path = f"/tmp/monitor_{uuid.uuid4().hex}.fifo"
        if os.path.exists(self.fifo_path):
            os.remove(self.fifo_path)
        os.mkfifo(self.fifo_path)

        reader_script = f"""
import os
path = {repr(self.fifo_path)}
while True:
    with open(path, "r") as f:
        frame = f.read()
    print({repr(CLEAR)}, end="", flush=True)
    print(frame, end="", flush=True)
"""
        try:
            self.proc = subprocess.Popen(
                ["alacritty", "-e", "python3", "-c", reader_script],
                preexec_fn=os.setsid
            )
            time.sleep(0.5)   # let the window come up before first frame
            if self.proc.poll() is not None:
                # alacritty exited immediately (no display server)
                self.proc = None
                self._go_headless(warn=False)
                return
            self._ready = True
        except Exception as e:
            self.proc = None
            self._go_headless(warn=False)
            print(f"MonitorWindow: could not spawn alacritty ({e}); "
                  "continuing headless.", file=sys.stderr)

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
        if self.proc is not None and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), 15)
            except Exception:
                pass
        if self.fifo_path and os.path.exists(self.fifo_path):
            try:
                os.remove(self.fifo_path)
            except Exception:
                pass
