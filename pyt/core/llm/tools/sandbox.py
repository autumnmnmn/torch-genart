
import subprocess
import threading
import signal
import shlex

from datetime import datetime
from typing import Literal, Optional

from pyt.core.llm.tools import tool, toolprop

date_fmt = "%d.%m.%Y t%H.%M.%S"

class Command:
    def __init__(self, agent, box_spec, program, args):
        self.program = program
        self.args = args
        self.agent = agent
        self.box_spec = box_spec
        self.stdout_content = ""
        self.stderr_content = ""
        self.stdin_content = ""
        self.stdout_stream = None
        self.stderr_stream = None
        self.finished = None
        self.start_time = None
        self._process = None
        self._lock = threading.Lock()  # guards *_content

    def _drain(self, stream, attr):
        for chunk in iter(lambda: stream.read(4096), b""):
            with self._lock:
                setattr(self, attr, getattr(self, attr) + chunk.decode(errors="replace"))

    def run(self):
        self.start_time = datetime.now()

        cmd = [
            "/usr/local/bin/in-box",
            self.box_spec,
            "--as", self.agent,
            "--capability", "gpu",
            "--no-pty",
            "--quiet",
            "--",
            self.program,
            *shlex.split(self.args)
        ]

        self._process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.stdout_stream = self._process.stdout
        self.stderr_stream = self._process.stderr
        threading.Thread(target=self._drain, args=(self._process.stdout, "stdout_content"), daemon=True).start()
        threading.Thread(target=self._drain, args=(self._process.stderr, "stderr_content"), daemon=True).start()

    def update(self):
        if self._process and self.finished is None and self._process.poll() is not None:
            self.finished = datetime.now()

    def stdin(self, text):
        if not text.endswith("\n"):
            text = text + "\n"
        if self._process and self._process.stdin:
            self._process.stdin.write(text.encode())
            self._process.stdin.flush()
            self.stdin_content += text

    def interrupt(self):
        if self._process:
            self._process.send_signal(signal.SIGINT)

    def kill(self):
        if self._process:
            self._process.kill()
            self.finished = datetime.now()

    def render(self, index):
        self.update()
        started = self.start_time.strftime(date_fmt) if self.start_time else "not started"
        status = f"finished at {self.finished.strftime(date_fmt)}" if self.finished else "running"
        with self._lock:
            out = self.stdout_content or ""
            err = self.stderr_content or ""
            _in = self.stdin_content or ""
        return f"[command #{index} \"{self.program} {self.args}\" | started: {started} | status: {status}]\n```stdin\n{_in}\n```\n\n```stdout\n{out}\n```\n\n```stderr\n{err}\n```\n[end of command #{index} \"{self.program}\"]"



@tool
class run_program:
    """Run a program in your home directory.

    This will run a SINGLE PROGRAM. There is NO PIPING and NO STREAM REDIRECTION.

    You can get around that limitation by running commands through `bash` with the `-c` flag like: `-c "complicated piping operation here"`.

    You can also run programs interactively. While a program is running, you will be able to pass input into its standard input stream. You can have multiple programs open at a time."""

    program: str = toolprop(desc="the program you want to run")
    cli_args: str = toolprop(desc="CLI args for the program. This cannot include piping operations or stream redirection.")
    #capabilities: str = toolprop(desc="comma-separated list of elevated capabilities needed for the program to run. these can include `network`, `gpu`, and `gui`. these commands may block while awaiting user approval")

    def handler(agent, session, args):
        command = Command(session.snapbox_name, session.box_spec, args.program, args.cli_args)

        index = session.get("_next_command_index") or 0
        session._next_command_index = index + 1

        session.commands[index] = command

        command.run()

        try:
            command._process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass

        session.thoughts.append(f"Ran a command (#{index}: {args.program})")

        #if args.program == "bash" and "python" in args.cli_args:
        #    session.thoughts.append("[automatic] Looks like you wrote 'python' in a bash command. This message is to remind you that running python through bash will bypass your venv and use the system python installation, which does not have all the packages you expect. You have to use python *directly* to access your sandbox's venv properly.")

        #if args.program == "bash" and "-ls" in args.cli_args[:5]:
        #    session.thoughts.append("[automatic] Looks like you passed -ls as flags to bash. That creates an interactive session. You may have meant to write `-c ls`.")

@tool
class send_input:
    """Send text to a command's standard input stream"""
    command_index: int = toolprop(desc="Index (#) of the command")
    text: str = toolprop(desc="Text to write to stdin. A newline will be appended to the end automatically.")

    def handler(agent, session, args):
        session.commands[args.command_index].stdin(args.text)
        session.thoughts.append(f"Sent input to command #{args.command_index}")

@tool
class interrupt_command:
    """Send SIGINT to a running command (ctrl-c)"""
    command_index: int = toolprop(desc="Index (#) of the command")

    def handler(agent, session, args):
        session.commands[args.command_index].interrupt()
        session.thoughts.append(f"Sent SIGINT to command #{args.command_index}")

@tool
class kill_command:
    """Terminate a command."""
    command_index: int = toolprop(desc="Index (#) of the command")

    def handler(agent, session, args):
        session.commands[args.command_index].kill()
        session.thoughts.append(f"Killed command #{args.command_index}")

@tool
class discard_command:
    """Discard a command, clearing it from the list. If the command has not yet finished running, this will also terminate it."""
    command_index: int = toolprop(desc="Index (#) of the command")

    def handler(agent, session, args):
        cmd = session.commands[args.command_index]
        if cmd.finished is None:
            cmd.kill()
        del session.commands[args.command_index]
        session.thoughts.append(f"Discarded command #{args.command_index}")

@tool
class wait_for_command:
    """Block until one or all commands finish. If command_index is omitted, waits on all running commands."""
    command_index: Optional[int] = toolprop(desc="Index (#) of the command. If omitted, waits on all running commands")
    timeout: float = toolprop(desc="Seconds to wait (max 60)")

    def handler(agent, session, args):
        timeout = min(args.timeout, 60.0)

        index = args.get("command_index")

        targets = (
            [session.commands[index]] if index is not None
            else [cmd for cmd in session.commands.values() if cmd.finished is None]
        )
        if not targets:
            return "no running commands"
        deadline = datetime.now().timestamp() + timeout
        for cmd in targets:
            remaining = deadline - datetime.now().timestamp()
            if remaining <= 0:
                break
            try:
                cmd._process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                pass
            cmd.update()

