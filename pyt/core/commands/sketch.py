
from argparse import ArgumentParser

from pyt.core.commands.commands import registrar_attr

_builtins = []
_builtin = registrar_attr(_builtins)

def register_builtins(group):
    group += _builtins

@_builtin("flush")
def _flush_state(session, args):
    import gc
    import sys
    session.persistent_state = {}
    session.persistent_hashes = {}
    gc.collect()
    if "torch" in sys.modules:
        torch = sys.modules["torch"]
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    session.log("state flushed")

new_parser = ArgumentParser("new")
new_parser.add_argument("name", type=str, help="Name of the new sketch")
new_parser.add_argument("--template", "-t", type=str, default=None,
                        help="Template to use (verbose, basic, or path to file)")

@_builtin("new", arg_parser=new_parser)
def _new_sketch(session, args):
    import shutil

    from pathlib import Path

    from pyt.core.terminal.ansi import codes as ac

    log = session.log

    template = args.template or session.env.get("TEMPLATE") or "verbose"

    if template in ["verbose", "basic"]:
        from importlib import import_module
        template_module = import_module(f"pyt.core.templates.{template}")
        template = Path(template_module.__file__)
    elif isinstance(template, Path):
        if not template.exists():
            log(f"template file not found: {template}", mode="error")
            return
    elif isinstance(template, str):
        try:
            template = Path(template)
        except:
            log("template could not be interpreted as a path", mode="error")
            return
        if not template.exists():
            log(f"template file not found: {template}", mode="error")
            return
    else:
        log("template could not be interpreted as a path", mode="error")
        return

    sketch_dir = session.env.SKETCH
    new_sketch = sketch_dir / f"{args.name}.py"

    if new_sketch.exists():
        log(f"sketch {args.name} already exists", mode="error")
        return

    shutil.copy(template, new_sketch)
    sketch_link = ac.file_link(new_sketch)
    template_link = ac.file_link(template)

    log(f"created {sketch_link} from template {template_link}", mode="ok")

@_builtin("rrun")
def _reload_run(session, args):
    if session.try_handle_command("reload", ""):
        session.try_handle_command("run", args)

@_builtin("run")
def _run(session, args):
    import os
    import sys
    import inspect
    import time
    import shutil
    from pathlib import Path
    from time import perf_counter
    from importlib import import_module

    from pyt.core.sketch.run import run, handle_persistent
    from pyt.core import lsnap

    sketch_name, remainder = lsnap(args)

    log = session.log

    try:
        log(f"loading sketch \"{sketch_name}\"", mode="info")
        module_name = f"{sketch_name}"
        if module_name in sys.modules:
            del sys.modules[module_name]
        sys.path.insert(0, str(session.env.SKETCH))
        sketch = import_module(module_name)
        sys.path.pop(0)
    except ModuleNotFoundError:
        log.indented().trace()
        log("no such sketch", mode="error", indent=4).blank()
        return
    except KeyboardInterrupt:
        log("aborted", mode="info").blank()
        return
    except SystemExit:
        raise
    except:
        log.indented().trace()
        return

    sources = { name : inspect.getsource(member)
                for name, member in inspect.getmembers(sketch)
                if inspect.isfunction(member) and member.__module__ == module_name
               }

    log = log.tag(sketch_name).mode("info")

    t0 = perf_counter()
    if hasattr(sketch, "persistent"):
        if not handle_persistent(session, sketch_name, sketch.persistent, sketch.__dict__, log, sources):
            log.blank()
            return

    sketch.__dict__.update(session.persistent_state)

    pyt_out = session.env.OUT

    if not pyt_out:
        session.log("no output directory has been specified.\nset via --out flag, or session.env.OUT in your ~/.config/pytrc.py, or by setting the PYT_OUT environment variable", mode="error")
        session.log("aborting.", mode="error")
        return

    daily = time.strftime("%d.%m.%Y")
    moment = time.strftime("t%H.%M.%S")

    run_dir = Path(os.path.join(pyt_out, sketch_name, daily, moment))
    sketch.__dict__["run_dir"] = run_dir
    run_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(sketch.__file__, run_dir / f"{sketch_name}.py")

    sketch.__dict__["args"] = remainder

    with open(run_dir / f".snakepyt", "w") as metadata:
        metadata.write(f"snakepyt version {session.snakepyt_version[0]}.{session.snakepyt_version[1]}\n")

    if hasattr(sketch, "main"):
        if hasattr(sketch, "final"):
            finalizer = sketch.final.__code__
        else:
            finalizer = None
            failures, runs = 0, 0
        try:
            failures, runs = run(session, sketch.main, None, (), sketch.__dict__, log, sources, finalizer)
        except KeyboardInterrupt:
            log.blank().log("aborted", mode="info").blank()
            return
    else:
        log("sketch has no main function", mode="error", indent=4)
        return

    if failures == 0:
        log(f"finished {runs} run(s) in {perf_counter() - t0:.3f}s", mode="ok")
    elif failures < runs:
        log(f"finished {runs-failures} of {runs} run(s) in {perf_counter() - t0:.3f}s", mode="info")
        log(f"{failures} run(s) failed to finish", mode="error")
    else:
        log(f"all {failures} run(s) failed to finish", mode="error")

