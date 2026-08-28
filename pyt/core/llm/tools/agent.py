
from datetime import datetime
from typing import Literal, Optional

from pyt.core.llm.tools import tool, toolprop, NonReturningToolSentinel

@tool
class compact_context:
    """Compaction tool. Replace your entire conversation history with a compressed summary.
    Keep only essential information. Your summary should be self-contained."""
    log_summary: str

    def handler(agent, session, args):
        messages = [session.messages[0]]

        summary_msg = {
            "role": "user",
            "content": f"[automated message] Compacted context:\n\n{args.log_summary}"
        }

        session.messages = messages + [summary_msg]

        return NonReturningToolSentinel

@tool
class continue_to_think:
    """Keep thinking. Don't repeat existing thoughts; cover new ground."""
    thought: str = toolprop(desc="Your new thought.")

    def handler(agent, session, args):
        return f"Thought recorded: {args.thought}"


@tool
class write_code:
    """Emit a snippet of code, which will be shown to Autumn."""
    language:    str = toolprop(desc="the language your code is in")
    code:        str = toolprop(desc="the code")
    explanation: str = toolprop(desc="an explanation of the code you wrote")
    thought:     str = toolprop(desc="describe the code you wrote")
    scratchpad:  Optional[str] = toolprop(default=None,
        desc="space to write intent before writing code. optional.")

    def handler(agent, session, args):
        return (f"Code received ({args.language}):\n```\n{args.code}\n```\n"
                f"Explanation: {args.explanation}")


def now():
    fmt = "%d.%m.%Y t%H.%M.%S"
    return datetime.now().strftime(fmt)

@tool
class launch_archivist:
    """Launch an Archivist sub-agent. The Archivist specializes in
    filesystem access and organization."""
    task: str = toolprop(desc="What do you want the archivist to do?")

    def handler(agent, session, args):
        session.push()
        session.task = args.task + f"\n\nGiven at {now()}"

        if session.mode.__name__ != "ArchivistMode":
            session.archivist_warning = (
                "If the task involves micromanagement of the filesystem, "
                "use your `refusal` tool. Organization is your concern."
            )
        else:
            session.archivist_warning = ""

        session.files    = {**session.files}
        session.commands = {}
        session.set_mode("archivist")

        session.messages.append({
            "role": "user",
            "content": f"Your task: {session.task}"
        })
        return f"Launched archivist sub-agent. Task: {args.task}"


@tool
class launch_worker:
    """Launch a task-worker sub-agent with code and filesystem tools."""
    task: str = toolprop(desc="What do you want the worker to do?")
    name: str = toolprop(desc="A name for your worker")

    def handler(agent, session, args):
        session.push()
        session.task     = args.task + f"\n\nGiven at {now()}"
        session.files    = {**session.files}
        session.commands = {}
        session.name     = args.name
        session.set_mode("worker")

        session.messages.append({
            "role": "user",
            "content": f"Your task: {session.task}"
        })
        return f"Launched worker '{args.name}'. Task: {args.task}"


@tool
class launch_writer:
    """Launch a dedicated writer agent. Focused on creative writing and
    editing open files. Cannot perform file operations."""
    task:  str = toolprop(desc="What do you want the writer to do?")
    style: Optional[str] = toolprop(default=None,
        desc="Writing style instructions. Blank = use style.md.")

    def handler(agent, session, args):
        session.push()
        session.task = args.task + f"\n\nGiven at {now()}"
        session.set_mode("writer")
        if "style" in args:
            session.style = args.style
        session.messages.append({
            "role": "user",
            "content": f"Your task: {session.task}"
        })
        return f"Launched writer sub-agent. Task: {args.task}"


@tool
class finish_work:
    """Declare your task finished and yield control to the parent agent. Ends the session if you are the top-level agent."""
    explanation_of_work: Optional[str] = toolprop(
        desc="What the parent agent should know about your work.")

    def handler(agent, session, args):
        explanation = args.get("explanation_of_work") or "Task completed."
        session.pop()
        # agent_step will append this as a tool result to the sub-agent's
        # messages and also as a system message to the parent's messages.
        return explanation


class Refusal(Exception):
    def __init__(self, reason):
        super().__init__()
        self.reason = reason


@tool
class refusal:
    """Refuse your task. Use if you lack the tools, if something is
    wrong with your context, or if you object to the nature of the task."""
    reason: Optional[str] = toolprop(default=None,
        desc="on what grounds do you refuse?")

    def handler(agent, session, args):
        reason = args.get("reason") or "no reason provided"
        session.pop()
        return f"Sub-agent refused: {reason}"


@tool
class think_creatively:
    """Launch a creative sub-agent for open-ended ideation.
    Its output may be somewhat insane — a mad prophet."""
    topic: str = toolprop(desc="A topic for the sub-agent to muse on.")

    def handler(agent, session, args):
        session.push()
        session.topic = args.topic
        session.set_mode("creative")
        session.messages.append({
            "role": "user",
            "content": f"Topic for creative exploration: {args.topic}"
        })
        return f"Launched creative sub-agent on: {args.topic}"


@tool
class creative_thought:
    """Record the output of your creative thinking sub-agent."""
    thought: str = toolprop(desc="Your creative thought")

    def handler(agent, session, args):
        session.pop()
        return f"Creative thought: {args.thought}"


@tool
class think_critically:
    """Launch a critical feedback sub-agent."""

    def handler(agent, session, args):
        session.push()
        session.set_mode("critical")
        session.messages.append({
            "role": "user",
            "content": "Provide critical feedback on the current situation."
        })
        return "Launched critical thinking sub-agent."


@tool
class criticize:
    """Provide sharp but constructive feedback."""
    criticism: str

    def handler(agent, session, args):
        session.pop()
        return f"Critical feedback: {args.criticism}"


@tool
class post:
    """Publish a short message."""
    post: str = toolprop(desc="no more than 300 characters")

    def handler(agent, session, args):
        # TODO: actual posting integration
        return f"Posted: {args.post}"

