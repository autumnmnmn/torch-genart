
import shlex
import sys

from argparse import ArgumentParser, ArgumentError

from pyt.core import lsnap
from pyt.core.terminal.ansi import codes as ac

def _apply_parser(behavior, parser):
    parser.exit_on_error = False
    def _behavior(session, args):
        try:
            _args = parser.parse_args(shlex.split(args))
            behavior(session, _args)
        except ArgumentError:
            session.log(parser.format_usage(), mode="info", indent=4)
            raise
    return _behavior

def register(group, behavior, *aliases, arg_parser=None):
    if any(" " in alias for alias in aliases):
        raise RuntimeError("spaces are not permitted in command aliases!")

    if isinstance(arg_parser, ArgumentParser):
        behavior = _apply_parser(behavior, arg_parser)

    group.append((list(aliases), behavior))

# looks arcane but it's just chopping register up for attribute-style usage:
# cmd = registar_attr(some_cmd_group)
# @cmd("some", "aliases", arg_parser=ap)
# def foo: ...
registrar_attr = lambda g: lambda *a, arg_parser=None: lambda b: register(g, b, *a, arg_parser=arg_parser)

_builtins = []
_builtin = registrar_attr(_builtins)

def register_builtins(group):
    group += _builtins

@_builtin("exit", "quit", ":q", ",q")
def _exit(session, args):
    session.log.blank().log(f"goodbye {session.persona.smile()}").blank()
    session.repl_continue = False

@_builtin("cmds")
def _commands(session, args):
    from pyt.core.terminal.ansi import codes as ac
    fg = ac.ansi(ac.fg("cyan"))
    bg = ac.ansi(ac.fg("cyan"), ac.mode("dim"))
    res = "commands:\n" + "\n".join([f" {bg}aka{ac.reset} ".join(f'{bg}"{ac.reset}{fg}' + y + f'{ac.reset}{bg}"{ac.reset}' for y in x[0]) for x in session.commands.all_available])
    session.log(res)

@_builtin("hello", "hi")
def _hi(session, args):
    session.log(f"{session.persona.hello()} {session.persona.smile()}")

@_builtin("reload", "refresh", "rr")
def _reload(session, args):
    import sys

    from importlib import reload

    from pyt.core import lsnap

    log = session.log

    session_reload = False

    # TODO find a robust way to track which files have actually changed
    for name, module in list(sys.modules.items()):
        if name.startswith("pyt"):
            try:
                reload(module)
                log(f"reloaded {name}")
                if name == "pyt.core.session":
                    session_reload = True
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                log.indented().trace()
                log(f"failed to reload {name}", mode="error")

    if session_reload:
        new_session_module = sys.modules["pyt.core.session"]
        session.update_class(new_session_module.PytSession)

    (cmd, remaining) = lsnap(args)
    if cmd == "&":
        (cmd, args) = lsnap(remaining)
        session.try_handle_command(cmd, args)

@_builtin("prefix", "pfx", "pre")
def _prefix(session, args):
    if args == ";":
        session.try_handle_command("bash", "")
        return

    session.prefix = args

def _get_default_shell():
    if sys.platform == "win32":
        return "powershell"
    elif sys.platform == "darwin":
        return "zsh"
    else:
        return "bash"

def _get_shell_cmd_flags(shell):
    if shell == "powershell":
        return ["-NonInteractive", "-Command"]
    else:
        return ["-ic"]

_shell = _get_default_shell()
_shell_cmd_flags = _get_shell_cmd_flags(_shell)

@_builtin("do", ";")
def _shell_do(session, args):
    import subprocess

    subprocess.run(
        [_shell] + _shell_cmd_flags + [args]
    )

@_builtin(_shell, ":")
def _shell_run(session, args):
    import os
    import subprocess

    log = session.log

    if args == "":
        log(f"switching to {_shell}!", mode="info")
        subprocess.run([_shell])
        log("wb bestie!")
        return

    args = session.favorite_dirs.get(args, args)

    path = os.path.expandvars(os.path.expanduser(args))

    if not os.path.isdir(path):
        log(f"{args} is not a directory but that's ok", mode="warning")
        log(f"switching to {_shell}", mode="info")
        subprocess.run([_shell])
        log("welcome back")
    else:
        log(f"switching to {_shell}, working directory {path}", mode="info")
        subprocess.run([_shell], cwd=path)
        log(f"back in the pyt {session.persona.smile()}")

@_builtin("faves", "ff")
def _faves(session, args):
    from pyt.core.terminal.ansi import codes as ac
    links = ["Favorite Directories:"]
    dirs = session.favorite_dirs
    for key in dirs.keys():
        cyan = ac.ansi(ac.fg('cyan'))
        links.append("    " + ac.file_link(dirs[key], text=f"{cyan}{key}{ac.reset} -> {dirs[key]}"))
    session.log("\n".join(links))

def _python_subprocess(session):
    import subprocess

    from pyt.core.terminal.ansi import codes as ac

    log = session.log

    log("switching to python!", mode="info")

    if session.env.PYTHON_PATH != None:
        try:
            subprocess.run([session.env.PYTHON_PATH, "-q"])
        except FileNotFoundError:
            link = ac.link(f"file://{session.env.PYTHON_PATH}", "preferred python")
            log(f"your {link} didn't load. trying system python :/", mode="warning")
            subprocess.run(["python", "-q"])
    else:
        subprocess.run(["python", "-q"])

    log("wb bestie!")

def _python_stateful(session):
    log = session.log
    log("entering python mode. persistent state is available", mode="info")

    state = dict(session.persistent_state)
    state["session"] = session
    state["print"] = log.tag("python")
    state["_print"] = print

    state.update(session.injected_state())

    from pyt.core.terminal.pywrapl import repl

    # TODO on_version_mismatch from pytrc
    repl(local=state, log=log, on_version_mismatch="warning")

    log(f"back to snakepyt {session.persona.smile()}")

@_builtin("python", "py", "'")
def _python(session, args):
    if args == "fresh":
        _python_subprocess(session)
    else:
        if args != "":
            session.log(f"i dunno what u expect me to do w/ that argument {session.persona.laugh()}", mode="info")
        _python_stateful(session)

