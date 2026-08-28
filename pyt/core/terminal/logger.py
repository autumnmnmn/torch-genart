
import sys
import inspect
import traceback
import time

from dataclasses import dataclass, replace
from typing import Optional
from pathlib import Path
from pprint import pformat

from pyt.core.terminal.ansi import codes as ac

_tag_colors = {
    "error": ac.ansi(ac.fg("red")),
    "ok": ac.ansi(ac.bright_fg("green")),
    "warning": ac.ansi(ac.fg("yellow")),
    "info": ac.ansi(ac.fg("cyan")),
    "unset": ac.ansi(ac.fg("cyan"))
}

_a11y_tags = {
    "error": "error",
    "ok": "",
    "warning": "warning",
    "info": "info",
    "unset": ""
}

def _log(tag, content, mode, indent, use_a11y_tags):
    tag_color = _tag_colors.get(mode, _tag_colors["unset"])
    if use_a11y_tags:
        a11y_tag = _a11y_tags.get(mode, "")
        tag = f"{tag} | {a11y_tag}" if a11y_tag != "" else tag
    print(f"{tag_color}{' '*indent}[{tag}]{ac.reset} {content}{ac.reset}")

def _input(prompt, mode, indent):
    tag_color = ac.ansi(ac.fg("magenta"))
    reset = ac.reset
    if "readline" in sys.modules and sys.stdin.isatty() and sys.stdout.isatty():
        tag_color = f"\001{tag_color}\002"
        reset = f"\001{reset}\002"
    return input(f"{tag_color}{' '*indent}{prompt} {reset}")

@dataclass(frozen=True)
class Logger:
    _mode: str = "unset"
    _indent: int = 0
    _tag: Optional[str] = None
    # TODO this toggle should be presented to a user the first time they
    # run snakepyt, and preference kept in pytrc
    _use_a11y_tags: bool = False
    _on_except: Callable[[Exception],None] | None = None

    def indented(self, n=4):
        return replace(self, _indent=self._indent + n)

    def tag(self, tag: Optional[str]):
        return replace(self, _tag=tag)

    def mode(self, mode: str):
        return replace(self, _mode=mode)

    def on_except(self, handler):
        return replace(self, _on_except=handler)

    def __call__(self, content, mode=None, indent=None, tag=None):
        if mode is None:
            mode = self._mode
        if indent is None:
            indent = self._indent
        if tag is None:
            tag = self._tag
        if tag is None:
            callsite = inspect.stack()[1]
            filepath = callsite[1]
            line_number = callsite[2]
            filename = Path(filepath).name
            tag = ac.file_link(filepath, line=line_number)
        if isinstance(content, dict):
            content = "\n"+pformat(content)
        _log(tag, content, mode, indent, self._use_a11y_tags)
        return self

    def trace(self, source=None):
        exception_type, exception, trace = sys.exc_info()
        if self._on_except is not None:
            self._on_except(exception)

        if exception_type is None:
            raise RuntimeError("Logger.trace was called in a context without an exception to trace")
        trace_frames = traceback.extract_tb(trace)
        tag = "error" if self._tag is None else self._tag
        exception_content = f"{exception_type.__name__}: {exception}"
        _log(tag, exception_content, mode="error", indent=self._indent, use_a11y_tags=self._use_a11y_tags)
        for frame in trace_frames[::-1]:
            file, line_number, function, line = frame
            if file == "<string>" and source is not None:
                file = inspect.getfile(source)
                lines, first_line = inspect.getsourcelines(source)
                if line_number < len(lines):
                    line = lines[line_number-1].strip()
                    line_number = first_line + line_number - 1
                else:
                    # TODO try and set up some gnarly errors to see if i can get this path to happen
                    # i *think* the improvements to the sketch AST modification have obviated this
                    _log(f"SNAKEPYT", "TRACING ERROR", mode="error", indent=self._indent+8, use_a11y_tags=self._use_a11y_tags)
            file_end = Path(file).name
            frame_tag = ac.file_link(file, line=line_number)
            _log(f"in {frame_tag}", line, mode="error", indent=self._indent+4, use_a11y_tags=self._use_a11y_tags)
        return self

    def log(self, content, mode=None, indent=None, tag=None):
        return self(content, mode, indent, tag)

    def blank(self):
        print()
        return self

    def input(self, fore):
        if fore is None:
            fore = ":"
        return _input(f"{fore}", mode="user", indent=self._indent)

