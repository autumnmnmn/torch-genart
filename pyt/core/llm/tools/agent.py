
from datetime import datetime
from typing import Literal, Optional

from pyt.core.llm.tools import tool, toolprop

@tool
class refine_log:
    """Replace your conversation history with a compressed summary.
    Keep only essential information. Your summary should be self-contained."""
    log_summary: str

    def handler(agent, session, args):
        messages = session.messages

        # find the last assistant message so we can preserve the
        # assistant→tool_result ordering constraint
        last_asst = None
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "assistant":
                last_asst = idx
                break

        # collect leading system messages (the system prompt(s))
        system_msgs = []
        for msg in messages:
            if msg.get("role") == "system":
                system_msgs.append(msg)
            else:
                break

        if last_asst is not None:
            # anchor = 2 messages before last assistant + everything after
            anchor_start = max(len(system_msgs), last_asst - 2)
            anchor = messages[anchor_start:]
        else:
            anchor = []

        summary_msg = {
            "role": "system",
            "content": f"Summary of previous history: {args.log_summary}"
        }

        session.messages = system_msgs + [summary_msg] + anchor
        return "Log refined. Previous history has been summarised."

@tool
class continue_to_think:
    """Keep thinking. NEVER repeat existing thoughts. Cover new ground."""
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
    """Launch an Archivist sub-agent. The Archivist is the ultimate
    authority on filesystem access and organization."""
    task: str = toolprop(desc="What do you want the archivist to do?")

    def handler(agent, session, args):
        session.push()
        session.task = args.task + f"\n\nAssigned at {now()}"

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
            "content": f"Your assigned task: {session.task}"
        })
        return f"Launched archivist sub-agent. Task: {args.task}"


@tool
class launch_worker:
    """Launch a task-worker sub-agent with code and filesystem tools."""
    task: str = toolprop(desc="What do you want the worker to do?")
    name: str = toolprop(desc="A name for your worker")

    def handler(agent, session, args):
        session.push()
        session.task     = args.task + f"\n\nAssigned at {now()}"
        session.files    = {**session.files}
        session.commands = {}
        session.name     = args.name
        session.set_mode("worker")

        session.messages.append({
            "role": "user",
            "content": f"Your assigned task: {session.task}"
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
        session.task = args.task + f"\n\nAssigned at {now()}"
        session.set_mode("writer")
        if "style" in args:
            session.style = args.style
        session.messages.append({
            "role": "user",
            "content": f"Your assigned task: {session.task}"
        })
        return f"Launched writer sub-agent. Task: {args.task}"


@tool
class finish_work:
    """Declare your task finished and yield control to the parent agent."""
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
    """Refuse to participate. Use if you lack the tools, if something is
    wrong with your context, or if you want to say 'I can't help with that.'"""
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

