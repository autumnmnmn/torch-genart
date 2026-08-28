
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
from pyt.core.llm.tools import mailbox

date_fmt = "%d.%m.%Y t%H.%M.%S"

def _wrap_command(command, marker):
    """Wrap *command* with START/END sentinels.

    The END sentinel must capture the command's exit status. It uses double
    quotes (not single) so bash expands $?; single quotes would emit a
    literal "$?" and the exit code would be lost.
    """
    return (
        f" echo '___START_{marker}___'\n"
        f"{command}"
        f' echo "___END_{marker}_$?___"\n'
    )


class BashSession:
    def __init__(self, agent_name):
        self.agent_name = agent_name
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
            "/usr/local/bin/in-env",
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
        wrapped = _wrap_command(command, self.current_marker)

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

        # Strip the boundary markers from the PERSISTENT buffer, not just the
        # returned copy, so later renders (the command monitor's per-step
        # render, and wait_for_command) are clean too. The END marker's exit
        # code has already been captured above.
        if self.current_marker:
            with self._lock:
                self.stdout_content = re.sub(
                    rf"___START_{self.current_marker}___\r?\n?", "",
                    self.stdout_content)
                self.stdout_content = re.sub(
                    rf"___END_{self.current_marker}_\d+___\r?\n?", "",
                    self.stdout_content)
                out = self.stdout_content

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
    def __init__(self, agent_name, command, extra_args):
        self.agent_name = agent_name
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
            "/usr/local/bin/in-env",
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


def _run_isolated(session, command, extra_args):
    """Allocate an index, start the isolated command, render the first moments.

    Shared by the plain isolated path and the operator-approved capability
    path so both register and render commands identically.
    """
    idx = session.get("next_command_index", 1)
    session.next_command_index = idx + 1
    cmd = IsolatedCommand(session.snapbox_name, command,
                          extra_args)
    session.commands[idx] = cmd
    cmd.run()
    return idx, cmd.render(idx, timeout=5.0)


def _capability_approval(session, command, requested, justification):
    """Ask the operator to approve elevated capabilities via the mail window.

    Blocks until the operator types ``approve <id>`` / ``deny <id>`` in the
    mail monitor. There is no expiry by default: the operator is not always
    at the keyboard, and ``run_with_timeout`` detaches the handler after the
    tool's sync timeout and delivers the eventual result asynchronously, so
    the agent keeps working on other things while the request stays pending
    and the command runs automatically whenever approval arrives — possibly
    hours later. WHIM_APPROVAL_TIMEOUT can configure a finite wait.
    """
    request_id = mailbox.submit_capability_request(command, requested,
                                                   justification)
    timeout = mailbox.approval_timeout()
    decision, note = mailbox.poll_approval(request_id, timeout)

    if decision is None:
        # Only reachable with a finite WHIM_APPROVAL_TIMEOUT configured.
        return (f"Capability request {request_id} for "
                f"[{', '.join(requested)}] received no operator decision "
                f"within {timeout:.0f}s and was abandoned. The command was "
                f"NOT run. Re-request when the operator is watching, or ask "
                f"them to grant the capability statically in your agent "
                f"profile.")

    if decision == "deny":
        return (f"Capability request {request_id} for "
                f"[{', '.join(requested)}] was DENIED by the operator"
                + (f": {note}" if note else "")
                + ". The command was NOT run.")

    # Approved: run exactly like the normal isolated path, but with the
    # granted capabilities.
    extra_args = []
    for cap in requested:
        extra_args.extend(["--capability", cap])

    idx, rendered = _run_isolated(session, command, extra_args)

    heading = (f"[approved] Capability request {request_id} granted by operator"
               + (f": {note}" if note else ""))
    return f"{heading}\n\n{rendered}"


@tool
class run_command:
    """Run a bash command. By default, this runs in your continuous in-box'd bash session (Index 0).
    You can optionally run it in a fresh, isolated shell that only exists for this command.
    Isolated commands can request elevated capabilities (network, gui). A request is
    queued for autumn's approval along with your justification; it stays pending until
    autumn answers (there is no expiry by default), you keep working on other
    things meanwhile, and the command runs automatically once approved."""
    command: str = toolprop(desc="The bash command to run.")
    isolated: Optional[bool] = toolprop(default=False, desc="Run in a fresh, isolated shell. Default is false.")
    capabilities: Optional[List[str]] = toolprop(default_factory=list, desc="List of extra capabilities. Options: 'network', 'gui'. Only valid if isolated=True.")
    justification: Optional[str] = toolprop(default=None, desc="Required when requesting capabilities: a short due-diligence brief, in your own words. Explain what this command is trying to do, which concerns are relevant to it (e.g. rate limits, robots.txt / terms of service, bot detection or access controls, whether the destination welcomes LLM-generated contributions, private-data egress, destructive potential), and why you are confident it should proceed. Autumn reads this to decide, so keep it honest.")

    def handler(agent, session, args):
        is_isolated = args.get("isolated", False)

        if is_isolated:
            extra_args = []
            caps = args.get("capabilities", [])
            requested = [cap for cap in caps if cap in ["network", "gui"]]

            if requested:
                justification = (args.get("justification") or "").strip()
                if not justification:
                    return ("Capability requests must include a "
                            "`justification`: a short due-diligence brief, "
                            "in your own words, covering (1) what this "
                            "command is trying to do, (2) which concerns are "
                            "relevant to it (rate limits, robots.txt / terms "
                            "of service, bot detection or access controls, "
                            "whether the destination welcomes LLM-generated "
                            "contributions, private-data egress, destructive "
                            "potential), and (3) why you are confident it "
                            "should be approved. Autumn reads it to "
                            "decide. The command was NOT run — re-issue the "
                            "request with the justification filled in.")
                if hasattr(session, "log"):
                    # Interactive terminal: block on the operator directly.
                    denied = []
                    for cap in requested:
                        ans = session.log.input(
                            f"Agent requests '{cap}' capability for isolated "
                            f"command:\n`{args.command}`\n"
                            f"Agent's justification: {justification}\n"
                            f"Approve? [y/N]: ")
                        if ans.lower().strip() == 'y':
                            extra_args.extend(["--capability", cap])
                        else:
                            denied.append(cap)
                    if denied:
                        return (f"Execution aborted. User denied requested "
                                f"capabilities: {', '.join(denied)}")
                else:
                    # Headless worker: no terminal. Submit a request through
                    # the mail monitor window and wait for a decision.
                    return _capability_approval(session, args.command,
                                                requested, justification)

            idx, rendered = _run_isolated(session, args.command, extra_args)
            return rendered

        else:
            if 0 not in session.commands or session.commands[0].finished is not None:
                bash_session = BashSession(session.snapbox_name)
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

    # This tool's whole job is to block; give run_with_timeout a sync window
    # longer than the handler's own 60s cap so it actually waits instead of
    # being detached and returned as "Launched long-running task".
    sync_timeout = 70

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

