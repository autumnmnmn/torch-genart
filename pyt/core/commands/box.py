
"""
Vibecoded - GLM 5.2

Pyt commands wrapping snapbox boxing operations.

These commands shell out to the snapbox CLI (`box`, `at-box`, `in-box`,
`peek`, `take`, `rmbox`, `rebox`, `lsbox`, `lssnap`, `snap`, `rmsnap`,
`save`, `collect`, `agent`). Favorite-directory shorthand (configured via
`session.favorite_dirs` in pytrc.py) is resolved for path-like arguments so
you can refer to faved directories by name instead of typing full paths.

Example pytrc.py:
    session.favorite_dirs = {
        "webui":     "/workspace/snakepyt/webui",
        "sketches":  "/workspace/pyt/sketch",
        "ml_models": "/run/media/ponder/ssd0/ml_models",
    }

Example pyt repl usage:
    box dev webui           # box named 'dev' from the 'webui' faved dir
    box dev                 # box named 'dev' of the current directory
    at-box dev              # enter the box
    peek dev                # inspect changes
    take dev                # promote changes back to the origin
    rmbox dev               # destroy the box
    lsbox                   # list all boxes
    in-box dev --home sketches -- bash
    collect webui           # collect textual files from webui faved dir
"""

import shlex
import subprocess

from pyt.core.commands.commands import registrar_attr

_builtins = []
_builtin = registrar_attr(_builtins)

def register_builtins(group):
    group += _builtins


# Options whose values are paths and should be faved-dir-resolved when present.
_PATH_OPTS = {"--home", "--bind", "--agent-externals", "--config-dir"}


def _split_args(args_str):
    if not args_str or not args_str.strip():
        return []
    try:
        return shlex.split(args_str)
    except ValueError:
        # fall back to whitespace split if shlex chokes (e.g. unclosed quote)
        return args_str.split()


def _resolve_faves(session, parts, positional_mode="all"):
    """Resolve faved directory shorthand in an argument list.

    positional_mode:
        "all"        - resolve every positional arg
        "skip_first" - leave the first positional alone (e.g. a box name),
                       resolve the rest
        "none"       - don't resolve any positional args (only resolve
                       values of path-like options like --home, --bind, etc.)

    After a `--` separator, nothing is resolved (everything is passed through
    verbatim, since it's typically the command to run inside the box).
    """
    faves = session.favorite_dirs
    if not faves:
        return list(parts)

    result = []
    skip_next = False
    first_pos_seen = False
    after_double_dash = False

    for arg in parts:
        if after_double_dash:
            result.append(arg)
            continue

        if skip_next:
            skip_next = False
            result.append(str(faves.get(arg, arg)))
            continue

        if arg == "--":
            after_double_dash = True
            result.append(arg)
            continue

        if arg.startswith("--"):
            base = arg.split("=", 1)[0]
            if "=" in arg:
                if base in _PATH_OPTS:
                    val = arg.split("=", 1)[1]
                    result.append(f"{base}={faves.get(val, val)}")
                else:
                    result.append(arg)
            else:
                if base in _PATH_OPTS:
                    skip_next = True
                result.append(arg)
            continue

        if arg.startswith("-") and len(arg) > 1:
            # short option or flag; pass through untouched
            result.append(arg)
            continue

        # Positional argument
        is_first = not first_pos_seen
        first_pos_seen = True

        if positional_mode == "none":
            result.append(arg)
        elif positional_mode == "skip_first" and is_first:
            result.append(arg)
        else:
            result.append(str(faves.get(arg, arg)))

    return result


def _run(session, cmd_name, parts, cwd=None):
    log = session.log.tag(cmd_name)
    display_parts = [cmd_name] + [shlex.quote(a) for a in parts]
    display = " ".join(display_parts)
    log(f"$ {display}", mode="info")

    try:
        # We use `bash -c` to execute the command so that PATH is searched
        # properly, and we bypass potential "Exec format error" issues if
        # the snapbox scripts have a shebang issue (e.g. CRLF line endings).
        # `"$@"` ensures properly quoted arguments are passed through safely.
        result = subprocess.run(
            ["bash", "-c", f'{cmd_name} "$@"', cmd_name, *parts],
            cwd=cwd
        )
        return result.returncode
    except FileNotFoundError:
        log(f"'bash' or '{cmd_name}' not found. is snapbox installed?", mode="error")
        return 127


# ──────────────────────────────────────────────────────────────────
# box / snap creation
# ──────────────────────────────────────────────────────────────────

@_builtin("box")
def _box(session, args):
    """Create a box from a directory or an existing snap.

    Faved dir shorthand is resolved for the target path (the second
    positional arg), but not for the box name (the first positional).

    Examples:
      box                    # auto-named box of current dir (or project root)
      box dev                # box named 'dev' of current dir
      box dev webui          # box named 'dev' from the 'webui' faved dir
      box dev /abs/path      # box named 'dev' from an absolute path
      box dev mysnap         # box named 'dev' from existing snap 'mysnap'
      box --size 16G dev webui
    """
    parts = _split_args(args)
    resolved = _resolve_faves(session, parts, positional_mode="skip_first")
    _run(session, "box", resolved)


@_builtin("snap")
def _snap(session, args):
    """Take a tmpfs snapshot of a directory.

    Faved dir shorthand is resolved for the path argument.

    Examples:
      snap                   # snap of current dir (or project root)
      snap webui             # snap of the 'webui' faved dir
      snap --local webui     # snap of faved dir without upward .snapbox search
    """
    parts = _split_args(args)
    resolved = _resolve_faves(session, parts, positional_mode="all")
    _run(session, "snap", resolved)


# ──────────────────────────────────────────────────────────────────
# box interaction
# ──────────────────────────────────────────────────────────────────

@_builtin("at-box", "atbox", "ab")
def _at_box(session, args):
    """Enter a box: launch a shell (or run a command) in the box's merged dir.

    Arguments are passed through verbatim — the first positional is a box
    name, and anything after it is a command + args that shouldn't be
    faved-resolved.

    Examples:
      at-box dev             # launch $SHELL inside box 'dev'
      ab dev ls -la          # run `ls -la` inside box 'dev'
    """
    parts = _split_args(args)
    _run(session, "at-box", parts)


@_builtin("in-env", "inbox", "ib")
def _in_box(session, args):
    """Launch an agent process with one or more boxes bound into its home.

    Box specs (positional args) are passed through unchanged, but path-like
    options (--home, --bind, --agent-externals, --config-dir) have faved dir
    shorthand resolved. Anything after `--` (the command to run) is left
    untouched.

    Example:
      in-box dev --home sketches -- bash
      ib dev,other --as myagent -- python script.py
    """
    parts = _split_args(args)
    resolved = _resolve_faves(session, parts, positional_mode="none")
    _run(session, "in-env", resolved)


@_builtin("peek")
def _peek(session, args):
    """View changes in a box without modifying the origin.

    Arguments (box name + optional file globs) are passed through verbatim.
    """
    parts = _split_args(args)
    _run(session, "peek", parts)


@_builtin("take")
def _take(session, args):
    """Promote box changes back to the origin directory.

    Arguments (box name + optional file globs) are passed through verbatim.
    """
    parts = _split_args(args)
    _run(session, "take", parts)


# ──────────────────────────────────────────────────────────────────
# box / snap lifecycle
# ──────────────────────────────────────────────────────────────────

@_builtin("rmbox")
def _rmbox(session, args):
    """Destroy a box (and clean up orphaned auto-managed snaps)."""
    parts = _split_args(args)
    _run(session, "rmbox", parts)


@_builtin("rebox")
def _rebox(session, args):
    """Re-snap the origin and re-mount the box on top of the fresh snap.

    Use `rebox <name> trample` to discard agent changes; without `trample`,
    agent changes in the upper layer are preserved.
    """
    parts = _split_args(args)
    _run(session, "rebox", parts)


@_builtin("rmsnap")
def _rmsnap(session, args):
    """Destroy a snap."""
    parts = _split_args(args)
    _run(session, "rmsnap", parts)


@_builtin("save")
def _save(session, args):
    """Archive a box or snap to persistent storage."""
    parts = _split_args(args)
    _run(session, "save", parts)


# ──────────────────────────────────────────────────────────────────
# listing
# ──────────────────────────────────────────────────────────────────

@_builtin("lsbox", "boxes")
def _lsbox(session, args):
    """List all boxes."""
    parts = _split_args(args)
    _run(session, "lsbox", parts)


@_builtin("lssnap", "snaps")
def _lssnap(session, args):
    """List all snaps."""
    parts = _split_args(args)
    _run(session, "lssnap", parts)


# ──────────────────────────────────────────────────────────────────
# utilities
# ──────────────────────────────────────────────────────────────────

@_builtin("collect")
def _collect(session, args):
    """Collect textual files from a project into a single document.

    Faved dir shorthand is resolved for the path argument.

    Example:
      collect webui          # collect from the 'webui' faved dir
      collect -c webui       # collect and copy to clipboard
      collect --xml webui    # XML output
    """
    parts = _split_args(args)
    resolved = _resolve_faves(session, parts, positional_mode="all")
    _run(session, "collect", resolved)


@_builtin("agent")
def _agent(session, args):
    """Manage agent profiles or launch an agent in a box.

    Subcommands: register, unregister, list, or <name> [command...]
    """
    parts = _split_args(args)
    _run(session, "agent", parts)

