
import subprocess
from typing import Optional

from pyt.core.llm.tools import tool, toolprop
from pyt.core.llm.tools.files import Document


@tool
class collect_source:
    """Gather every text file from a subtree of the project into a single document.

    Each file's relative path and full contents are presented together as one
    continuous document, injecting a snapshot of the codebase directly into your
    context."""

    path: str = toolprop(
        desc="The subdirectory to collect"
    )

    def handler(agent, session, args):

        cmd = ["in-env", "--as", agent.name, "--no-pty", "--", "collect", "--local", "-f"]

        if args.path:
            cmd.append(args.path)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
        except subprocess.TimeoutExpired:
            return "[collect timed out after 300 seconds]"

        if result.returncode != 0:
            error = result.stderr.strip() if result.stderr else "unknown error"
            return f"[collect failed: {error}]"

        text = result.stdout

        byte_count = len(text)
        line_count = text.count('\n')
        return text

