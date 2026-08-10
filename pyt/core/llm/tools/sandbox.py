
import subprocess
import threading
import signal
import shlex
import uuid
import re
import time

from datetime import datetime
from typing import Literal, Optional, List

from pyt.core.llm.tools import tool, toolprop

date_fmt = "%d.%m.%Y t%H.%M.%S"

class BashSession:
    def __init__(self, agent_name, box_spec):
        self.agent_name = agent_name
        self.box_spec = box_spec
        self.stdout_content = ""
        self.stderr_content = ""
        self.stdin_content = ""
        self.stdout_stream = None
        self.stderr_stream = None
        self.finished = None
        self.start_time = None
        self._process = None
        self._lock = threading.Lock()

        self.current_marker = None
        self.command_status = "idle"
        self.last_exit_code = None

    def _drain(self, stream, attr):
        for chunk in iter(lambda: stream.read1(4096), b""):
            with self._lock:
                setattr(self, attr, getattr(self, attr) + chunk.decode(errors="replace"))

    def run(self):
        self.start_time = datetime.now()

        cmd = [
            "/usr/local/bin/in-box",
            self.box_spec,
            "--as", self.agent_name,
            "--capability", "gpu",
            "--no-pty",
            "--quiet",
            "--",
            "stdbuf", "-oL", "bash"
        ]

        self._process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.stdout_stream = self._process.stdout
        self.stderr_stream = self._process.stderr
        threading.Thread(target=self._drain, args=(self._process.stdout, "stdout_content"), daemon=True).start()
        threading.Thread(target=self._drain, args=(self._process.stderr, "stderr_content"), daemon=True).start()

        # Initialize history and tell Bash to ignore commands starting with a space
        setup_commands = " set -o history\n export HISTCONTROL=ignorespace\n"
        self._process.stdin.write(setup_commands.encode())
        self._process.stdin.flush()

    def update(self):
        if self._process and self.finished is None and self._process.poll() is not None:
            self.finished = datetime.now()
            if self._process.returncode is not None:
                self.last_exit_code = self._process.returncode

    def run_command(self, command):
        if not command.endswith("\n"):
            command += "\n"

        self.current_marker = uuid.uuid4().hex
        self.command_status = "running"
        self.last_exit_code = None

        with self._lock:
            # Clear output buffers to cleanly capture just this command
            self.stdout_content = ""
            self.stderr_content = ""
            self.stdin_content = command

        # Notice the leading spaces! Bash will not record these in history.
        wrapped = (
            f" echo '___START_{self.current_marker}___'\n"
            f"{command}"
            f" echo '___END_{self.current_marker}_$?___'\n"
        )

        if self._process and self._process.stdin:
            self._process.stdin.write(wrapped.encode())
            self._process.stdin.flush()

    def stdin(self, text):
        if not text.endswith("\n"):
            text += "\n"
        with self._lock:
            self.stdin_content += text
        if self._process and self._process.stdin:
            self._process.stdin.write(text.encode())
            self._process.stdin.flush()

    def interrupt(self):
        if self._process:
            self._process.send_signal(signal.SIGINT)

    def kill(self):
        if self._process:
            self._process.kill()
            self.finished = datetime.now()
            self.last_exit_code = -9  # SIGKILL
            self.command_status = "finished"

    def render(self, index, timeout=0.0):
        self.update()

        if self.finished:
            status_str = f"session terminated at {self.finished.strftime(date_fmt)}"
        else:
            start_time = time.time()
            while True:
                with self._lock:
                    out = self.stdout_content

                # Check for completion marker
                if self.current_marker and f"___END_{self.current_marker}_" in out:
                    self.command_status = "finished"
                    match = re.search(rf"___END_{self.current_marker}_(\d+)___", out)
                    if match:
                        self.last_exit_code = match.group(1)
                    break

                # Check timeout
                if time.time() - start_time >= timeout:
                    break
                time.sleep(0.05)

            status_str = self.command_status
            if status_str == "finished" and self.last_exit_code is not None:
                status_str += f" (exit code {self.last_exit_code})"

        with self._lock:
            out = self.stdout_content
            err = self.stderr_content
            _in = self.stdin_content

        # Strip the boundary markers from the output sent to the agent
        if self.current_marker:
            out = re.sub(rf"___START_{self.current_marker}___\r?\n?", "", out)
            out = re.sub(rf"___END_{self.current_marker}_\d+___\r?\n?", "", out)

            if self.command_status == "finished":
                self.current_marker = None

        return (
            f"[bash session #{index} | status: {status_str}]\n"
            f"```stdin\n{_in.strip()}\n```\n\n"
            f"```stdout\n{out.strip()}\n```\n\n"
            f"```stderr\n{err.strip()}\n```\n"
            f"[end of bash session #{index}]"
        )


class IsolatedCommand:
    def __init__(self, agent_name, box_spec, command, extra_args):
        self.agent_name = agent_name
        self.box_spec = box_spec
        self.command = command
        self.extra_args = extra_args
        self.stdout_content = ""
        self.stderr_content = ""
        self.stdin_content = command + "\n"
        self.stdout_stream = None
        self.stderr_stream = None
        self.finished = None
        self.start_time = None
        self._process = None
        self._lock = threading.Lock()
        self.last_exit_code = None

    def _drain(self, stream, attr):
        for chunk in iter(lambda: stream.read(4096), b""):
            with self._lock:
                setattr(self, attr, getattr(self, attr) + chunk.decode(errors="replace"))

    def run(self):
        self.start_time = datetime.now()

        cmd = [
            "/usr/local/bin/in-box",
            self.box_spec,
            "--as", self.agent_name,
            "--capability", "gpu",
            *self.extra_args,
            "--no-pty",
            "--quiet",
            "--",
            "bash", "-c", self.command
        ]

        self._process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.stdout_stream = self._process.stdout
        self.stderr_stream = self._process.stderr
        threading.Thread(target=self._drain, args=(self._process.stdout, "stdout_content"), daemon=True).start()
        threading.Thread(target=self._drain, args=(self._process.stderr, "stderr_content"), daemon=True).start()

    def update(self):
        if self._process and self.finished is None and self._process.poll() is not None:
            self.finished = datetime.now()
            self.last_exit_code = self._process.returncode

    def stdin(self, text):
        if not text.endswith("\n"):
            text += "\n"
        with self._lock:
            self.stdin_content += text
        if self._process and self._process.stdin:
            self._process.stdin.write(text.encode())
            self._process.stdin.flush()

    def interrupt(self):
        if self._process:
            self._process.send_signal(signal.SIGINT)

    def kill(self):
        if self._process:
            self._process.kill()
            self.finished = datetime.now()
            self.last_exit_code = -9  # SIGKILL
            self.command_status = "finished"

    def render(self, index, timeout=0.0):
        self.update()

        if not self.finished:
            start_time = time.time()
            while True:
                self.update()
                if self.finished or time.time() - start_time >= timeout:
                    break
                time.sleep(0.05)

        status_str = f"finished at {self.finished.strftime(date_fmt)} (exit code {self.last_exit_code})" if self.finished else "running"

        with self._lock:
            out = self.stdout_content
            err = self.stderr_content
            _in = self.stdin_content

        return (
            f"[isolated command #{index} | status: {status_str}]\n"
            f"```stdin\n{_in.strip()}\n```\n\n"
            f"```stdout\n{out.strip()}\n```\n\n"
            f"```stderr\n{err.strip()}\n```\n"
            f"[end of isolated command #{index}]"
        )


@tool
class run_command:
    """Run a bash command. By default, this runs in your continuous in-box'd bash session (Index 0).
    You can optionally run it in a fresh, isolated shell that only exists for this command.
    Isolated commands can request elevated capabilities (network, gui) which will block on user approval."""
    command: str = toolprop(desc="The bash command to run.")
    isolated: Optional[bool] = toolprop(default=False, desc="Run in a fresh, isolated shell. Default is false.")
    capabilities: Optional[List[str]] = toolprop(default_factory=list, desc="List of extra capabilities. Options: 'network', 'gui'. Only valid if isolated=True.")

    def handler(agent, session, args):
        is_isolated = args.get("isolated", False)

        if is_isolated:
            extra_args = []
            caps = args.get("capabilities", [])
            requested = [cap for cap in caps if cap in ["network", "gui"]]

            # No interactive terminal in headless workers: deny cleanly instead of
            # crashing on session.log.input().
            if requested and not hasattr(session, "log"):
                return (f"Capability request denied: no interactive terminal is "
                        f"available for operator approval in this sandbox. "
                        f"Requested: {', '.join(requested)}. Run the command "
                        f"without requesting capabilities, or have the operator "
                        f"grant them statically in the agent profile.")

            denied = []
            for cap in requested:
                # Block on user input directly using the terminal logger
                ans = session.log.input(f"Agent requests '{cap}' capability for isolated command:\n`{args.command}`\nApprove? [y/N]: ")
                if ans.lower().strip() == 'y':
                    extra_args.extend(["--capability", cap])
                else:
                    denied.append(cap)

            if denied:
                return f"Execution aborted. User denied requested capabilities: {', '.join(denied)}"

            idx = session.get("next_command_index", 1)
            session.next_command_index = idx + 1

            cmd = IsolatedCommand(session.snapbox_name, session.box_spec, args.command, extra_args)
            session.commands[idx] = cmd
            cmd.run()

            return cmd.render(idx, timeout=5.0)

        else:
            if 0 not in session.commands or session.commands[0].finished is not None:
                bash_session = BashSession(session.snapbox_name, session.box_spec)
                bash_session.run()
                session.commands[0] = bash_session

            bash_session = session.commands[0]
            bash_session.run_command(args.command)

            return bash_session.render(0, timeout=5.0)


@tool
class restart_bash_session:
    """If your continuous bash environment (Command #0) becomes completely unresponsive or hopelessly broken, use this to kill the shell and start a fresh one. You will lose your current working directory and environment variables."""
    def handler(agent, session, args):
        cmd = session.commands.get(0)
        if cmd:
            if cmd.finished is None:
                cmd.kill()
            del session.commands[0]
            return "Continuous bash session (Command #0) has been terminated and cleared. A fresh one will start on your next run_command."
        return "No continuous bash session is currently running."


@tool
class send_input:
    """Send text to a command's standard input stream"""
    command_index: int = toolprop(desc="Index (#) of the command")
    text: str = toolprop(desc="Text to write to stdin. A newline will be appended to the end automatically.")

    def handler(agent, session, args):
        if args.command_index not in session.commands:
            return f"Command #{args.command_index} not found."
        session.commands[args.command_index].stdin(args.text)
        return f"Sent input to command #{args.command_index}:\n{args.text}"

@tool
class interrupt_command:
    """Send SIGINT to a running command (ctrl-c)"""
    command_index: int = toolprop(desc="Index (#) of the command")

    def handler(agent, session, args):
        if args.command_index not in session.commands:
            return f"Command #{args.command_index} not found."
        session.commands[args.command_index].interrupt()
        return f"Sent SIGINT to command #{args.command_index}"

@tool
class kill_command:
    """Terminate a command."""
    command_index: int = toolprop(desc="Index (#) of the command")

    def handler(agent, session, args):
        if args.command_index not in session.commands:
            return f"Command #{args.command_index} not found."
        session.commands[args.command_index].kill()
        return f"Killed command #{args.command_index}"

@tool
class discard_command:
    """Discard an isolated command (Index > 0), clearing it from the list. If it has not yet finished running, this will also terminate it. Do NOT use this for the continuous bash session (Index 0)."""
    command_index: int = toolprop(desc="Index (#) of the isolated command")

    def handler(agent, session, args):
        if args.command_index == 0:
            return "Error: Cannot discard Command #0 (continuous session). Use restart_bash_session instead."

        cmd = session.commands.get(args.command_index)
        if not cmd:
            return f"Command #{args.command_index} not found."
        if cmd.finished is None:
            cmd.kill()
        del session.commands[args.command_index]
        return f"Discarded isolated command #{args.command_index}"

@tool
class wait_for_command:
    """Block to allow a running command to accumulate output."""
    command_index: Optional[int] = toolprop(desc="Index (#) of the command. If omitted, waits on all running commands")
    timeout: float = toolprop(desc="Seconds to wait (max 60)")

    def handler(agent, session, args):
        timeout = min(args.timeout, 60.0)

        index = args.get("command_index")

        targets = []
        if index is not None:
            if index in session.commands:
                targets.append((index, session.commands[index]))
            else:
                return f"Command #{index} not found."
        else:
            targets = [(idx, cmd) for idx, cmd in session.commands.items() if cmd.finished is None]

        if not targets:
            return "no running commands"

        deadline = datetime.now().timestamp() + timeout
        renders = []
        for idx, cmd in targets:
            remaining = max(0.0, deadline - datetime.now().timestamp())
            renders.append(cmd.render(idx, timeout=remaining))

        return "Wait completed. Current command statuses:\n\n" + "\n\n".join(renders)

