
import os
import sys

from pathlib import Path

from pyt.core.terminal.ansi import codes as ac
from pyt.core import AttrDict, lsnap
from pyt.core.commands import registrar_attr, register_builtins
from pyt.core.websocket import WebsocketServer

def _find_pytrc():
    config_home = os.getenv("XDG_CONFIG_HOME")
    if not config_home:
        config_home = Path.home() / ".config"
    else:
        config_home = Path(config_home)

    snakepyt_dir = config_home / "snakepyt"
    snakepyt_dir.mkdir(parents=True, exist_ok=True)

    return snakepyt_dir / "pytrc.py"

class PytSession:
    def define_cli_args(parser):
        parse_str_list = lambda s: s.split(",")

        parser.add_argument("--out", dest="pyt_out", type=Path,
                            default=None,
                            help="Where to place sketch outputs")
        parser.add_argument("--in", dest="pyt_in", type=Path,
                            default=".",
                            help="Where to find input data for sketches (default: current working directory)")
        parser.add_argument("--sketches", dest="pyt_sketch", type=Path,
                            default=None,
                            help="Where to find sketches")
        parser.add_argument("--write", dest="write_flags", type=parse_str_list,
                            default=["pytfile","sketch","outputs"],
                            help="What to include in output directories",
                            metavar="pytfile,sketch,outputs,...")
        parser.add_argument("--pytrc", dest="pytrc", type=Path,
                            default=None,
                            help="Path of pytrc.py config file")
        parser.add_argument("--python", dest="python_path", type=Path,
                            default=None,
                            help="Path of preferred python interpreter")

    def _except_callback(self, exception):
        self.last_exception = exception

    def __init__(self, cli_args):
        self.cli_args = cli_args
        self.snakepyt_version = (0, 2)
        self.repl_continue = True

        self.prefix = None

        self.favorite_dirs = {}

        self.persistent_state = {}
        self.persistent_hashes = {}

        from pyt.core.terminal import Logger
        self.log = Logger().mode("ok").tag("snakepyt").on_except(self._except_callback)
        self.last_exception = None

        self.commands = AttrDict()

        self.env = AttrDict()

        self.load_pytrc()

        self._get_paths()

        self.socket = WebsocketServer(self.log.tag("socket"))

        from pyt.core.terminal import persona
        self.persona = persona.Persona.from_config(persona.default) # TODO configurable

        self.commands.builtin = []

        register_builtins(self.commands.builtin)

        self.commands.all_available = self.commands.user + self.commands.builtin

        # TODO store username
        try:
            username = os.getlogin()
        except:
            username = ""

        self.log(f"{self.persona.hello()} {username}! {self.persona.smile()}" if username else f"{self.persona.hello()}! {self.persona.smile()}")
        self.log.blank()

    def injected_state(self):
        return {
            **self.persistent_state,
            "send": self.socket.send,
            "receive": self.socket.receive
        }

    def _get_paths(self):
        # priority order: cli > pytrc > env > default

        # TODO next time a new env var is added, do the obvious refactor here
        self.env.OUT = self.cli_args.pyt_out or self.env.get("OUT") or os.getenv("PYT_OUT") or None
        self.env.IN = self.cli_args.pyt_in or self.env.get("IN") or os.getenv("PYT_IN") or Path(".")
        self.env.SKETCH = self.cli_args.pyt_sketch or self.env.get("SKETCH") or os.getenv("PYT_SKETCH") or Path(".")
        self.env.TEMPLATE = self.env.get("TEMPLATE") or os.getenv("PYT_TEMPLATE") or "verbose"
        self.env.PYTHON_PATH = self.cli_args.python_path or self.env.get("PYTHON_PATH") or os.getenv("PYTHON_PATH") or sys.executable

        if isinstance(self.env.OUT, str): self.env.OUT = Path(self.env.OUT)
        if isinstance(self.env.IN, str): self.env.IN = Path(self.env.IN)
        if isinstance(self.env.SKETCH, str): self.env.SKETCH = Path(self.env.SKETCH)

        if isinstance(self.env.PYTHON_PATH, str): self.env.PYTHON_PATH = Path(self.env.PYTHON_PATH)

    def load_pytrc(self):
        self.commands.user = []

        pytrc = self.cli_args.pytrc if self.cli_args.pytrc else _find_pytrc()

        log = self.log.tag(ac.file_link(pytrc))
        long_link = ac.file_link(pytrc, full=True)

        if not pytrc.exists():
            # TODO in the case where no pytrc exists but env vars have been passed as CLI args,
            # it would be preferable to generate a pytrc that sets those args as its defaults.

            self.log("no pytrc.py found. generating default configuration", mode="info")
            from importlib.resources import files
            import shutil

            template = files("pyt.core.templates").joinpath("pytrc.py")

            shutil.copy(template, pytrc)

            log.blank().log(f"generated pytrc.py at {long_link}. you can edit it to customize snakepyt. if you'd prefer to keep your configuration elsewhere, use the --pytrc flag to specify its location, or set the XDG_CONFIG_HOME environment variable.", mode="ok").blank()

        if pytrc.exists():
            namespace = {
                "command": registrar_attr(self.commands.user),
                "session": self,
                "print": log
            }
            try:
                with open(pytrc) as rcfile:
                    code = compile(rcfile.read(), filename=str(pytrc), mode="exec")
                    exec(code, namespace)
                log("loaded successfully", mode="ok")
            except (KeyboardInterrupt, SystemExit):
                raise
            except:
                log("encountered error in user configuration", mode="error")
                log.indented().trace()
                log("some configuration settings may not be loaded", mode="warning")

    def try_handle_command(self, command, remainder):
        for aliases, behavior in self.commands.all_available:
            if command in aliases:
                self.log = self.log.tag(aliases[0])
                behavior(self, remainder)
                return True
        return False

    def handle_message(self, message):
        log = self.log
        try:
            if self.prefix:
                if message in ["un", "unpre", "unprefix"]:
                    self.prefix = None
                    return
                message = " ".join([self.prefix, message])

            if message.startswith("."):
                if message.rstrip() == ".":
                    state_dump = "\n".join([f"    {k}: {type(v).__name__}" for k, v in self.persistent_state.items()])
                    log(f"base:\n{state_dump}")
                else:
                    segments = [segment.strip() for segment in message.split(".")][1:]
                    selection = ("base scope", self.persistent_state)
                    for segment in segments:
                        if segment == "":
                            log("repeated dots (..) are redundant", mode="warning")
                            return
                        try:
                            selection = (segment, selection[1][segment])
                            log(f"{selection[0]}: {selection[1]}")
                        except KeyError:
                            log(f"no \"{segment}\" in {selection[0]}", mode="error")
                            return
                        except TypeError:
                            log(f"{selection[0]} is not a scope", mode="error")
                            log.indented()(f"{selection[0]}: {selection[1]}", mode="info")

                return

            (command, remainder) = lsnap(message)

            if not self.try_handle_command(command, remainder):
                log(f"unknown command: {command}", mode="info")
        except:
            log.indented().trace()
        finally:
            self.log = log.tag("snakepyt")

    def update_class(self, new_class):
        try:
            new_instance = new_class(self.cli_args)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.log.trace()
            self.log("New session constructor failed. Session will not be updated.", mode="error")
            return

        state = self.persistent_state
        hashes = self.persistent_hashes
        prefix = self.prefix

        self.__class__ = new_instance.__class__
        self.__dict__.clear()
        self.__dict__.update(new_instance.__dict__)

        self.persistent_state = state
        self.persistent_hashes = hashes
        self.prefix = prefix

