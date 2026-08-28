from pathlib import Path
from pyt.core.llm.chatlog import load_chatlog
from pyt.core.llm.tools import tool
from pyt.core.llm.tools.agent import *
from pyt.core.llm.tools.files import *
from pyt.core.llm.tools.sandbox import *
from pyt.core.llm.tools.collect import collect_source
from pyt.core.llm.tools.vision import describe_image, look_at_image
from pyt.core.llm.tools.mailbox import send_operator_message, wait_for_operator

_chatlogs = Path(__file__).parent / "chatlog"

def _load_prompt(filename: str) -> str:
    """Loads a .literal system_prompt from the given chatlog file."""
    try:
        data = load_chatlog(_chatlogs / filename)
        # data.system_prompt will be the raw string from the .literal block
        return getattr(data, "system_prompt", "")
    except Exception as e:
        print(f"Warning: could not load system prompt from {filename}: {e}")
        return ""


class AgentMode:
    system_prompt = ""

    def get_tools(agent, session, step): ...

    def get_params(agent, session, step):
        return {}


class DefaultMode(AgentMode):
    system_prompt = _load_prompt("agent.cl")

    def get_tools(agent, session, step):
        tools = [
            #continue_to_think,
            #launch_worker,
            #new_note,
            #rewrite_note,
            #close_note,
            #update_self,
            #refusal
        ]
        if len(session.messages) > 20:
            tools.append(refine_log)
        return tools

    def get_params(agent, session, step):
        return {"temperature": 0.9}


class WorkerMode(AgentMode):
    system_prompt = _load_prompt("worker.cl")

    def get_tools(agent, session, step):
        tools = [
            run_command,
            finish_work,
            collect_source,
            launch_worker,
            compact_context,
            send_input,
            interrupt_command,
            wait_for_command,
            kill_command,
            restart_bash_session,
            discard_command,
            send_operator_message,
            wait_for_operator,
            refusal
        ]

        # a vision-capable model looks at images itself; anything else
        # outsources to a vision model
        if agent.get("has_vision"):
            tools.append(look_at_image)
        else:
            tools.append(describe_image)

        return tools

    def get_params(agent, session, step):
        return {"temperature": 0.9}


class CreativeMode(AgentMode):
    # Assuming you might split this into creative.cl later,
    # but for now keeping it pointed at agent.cl
    system_prompt = _load_prompt("agent.cl")

    def get_tools(agent, session, step):
        return [
            tool(creative_thought, desc=f"Think loosely and freely on the topic of {session.topic}. Try as hard as you can to stick to that topic, though, and to say something coherent and meaningful. Please do your best to keep it brief and end your message at a reasonable length."),
            refusal
        ]

    def get_params(agent, session, step):
        return {
            "temperature": 3.0,
            "top_p": 0.98,
            "min_p": 0.005
        }


class CriticalMode(AgentMode):
    system_prompt = _load_prompt("critic.cl")

    def get_tools(agent, session, step):
        return [
            criticize,
            refusal
        ]

    def get_params(agent, session, step):
        return {"temperature": 0.8}


class ArchivistMode(AgentMode):
    system_prompt = _load_prompt("archivist.cl")

    def get_tools(agent, session, step):
        tools = [
            #continue_to_think,
            #rewrite_document,
            #close_document,
            #new_document,
            #share_document,
            #run_command,
            #finish_work,
            #refusal
        ]
        #if len(session.messages) > 10:
            #tools.append(launch_archivist)
            #tools.append(launch_writer)
            #tools.append(launch_worker)
        #if len(session.messages) > 20:
            #tools.append(refine_log)
        #if any(c.finished is None for c in session.commands.values()):
            #tools.append(send_input)
            #tools.append(interrupt_command)
            #tools.append(wait_for_command)
            #tools.append(kill_command)
        #if len(session.commands) > 0:
            #tools.append(discard_command)
        return tools

    def get_params(agent, session, step):
        return {"temperature": 0.7}


class WriterMode(AgentMode):
    system_prompt = _load_prompt("writer.cl")

    def get_tools(agent, session, step):
        tools = [
            #continue_to_think,
            #rewrite_document,
            #new_document,
            #launch_archivist,
            #launch_worker,
            #think_creatively,
            #finish_work,
            #refusal
        ]
        #if len(session.messages) > 20:
            #tools.append(refine_log)
        return tools

    def get_params(agent, session, step):
        return {"temperature": 1.0}
