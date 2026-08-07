
from pathlib import Path

from pyt.core.llm.chatlog import load_chatlog
from pyt.core.llm.tools import tool
from pyt.core.llm.tools.agent import *
from pyt.core.llm.tools.files import *
from pyt.core.llm.tools.sandbox import *
from pyt.core.llm.tools.collect import collect_source

class AgentMode:
    def get_tools(agent, session, step): ...

    def get_template(agent, session, step): ...

    def prepare(agent, session, step): ...

_chatlogs = Path(__file__).parent / "chatlog"

class DefaultMode:
    def get_tools(agent, session, step):
        tools = [
            continue_to_think,
            launch_worker,
            new_note,
            rewrite_note,
            close_note,
            update_self,
            refusal
        ]
        if len(session.thoughts) > 2:
            tools.append(refine_log)
        return tools

    def get_template(agent, session, step):
        return load_chatlog(_chatlogs / "agent.cl").agent_ctx

    def prepare(agent, session, step):
        session.temperature = 0.9#max(0.4, 1.2 - 0.1 * len(session.thoughts))
        step["jinja_args"] = { "reply_as": agent.name }

class WorkerMode:
    def get_tools(agent, session, step):
        tools = [
            continue_to_think,
            rewrite_document,
            close_document,
            new_document,
            share_document,
            #save_or_load,
            #view_image,
            #move_file,
            #delete_file,
            #create_file,
            run_program,
            finish_work,
            collect_source,
            refusal
        ]
        if len(session.thoughts) > 1:
            tools.append(launch_worker)
        if len(session.thoughts) > 2:
            tools.append(refine_log)
        if any(c.finished is None for c in session.commands.values()):
            tools.append(send_input)
            tools.append(interrupt_command)
            tools.append(wait_for_command)
            tools.append(kill_command)
        if len(session.commands) > 0:
            tools.append(discard_command)
        if len(session.image_sources) > 0:
            tools.append(discard_image)
        return tools

    def get_template(agent, session, step):
        return load_chatlog(_chatlogs / "worker.cl").agent_ctx

    def prepare(agent, session, step):
        session.temperature = 0.9#max(0.4, 1.2 - 0.1 * len(session.thoughts))
        #step["jinja_args"] = { "reply_as": session.name }

class CreativeMode:
    def get_tools(agent, session, step):
        return [
            tool(creative_thought, desc=f"Think loosely and freely on the topic of {session.topic}. Try as hard as you can to stick to that topic, though, and to say something coherent and meaningful. Please do your best to keep it brief and end your message at a reasonable length."),
            refusal
        ]

    def get_template(agent, session, step):
        return load_chatlog(_chatlogs / "agent.cl").agent_ctx

    def prepare(agent, session, step):
        session.temperature = 3.0 # needs to be tuned per-model tbh
        #tool_call_kwargs["n_predict"] = 1 # prevent neverending rambles
        step["top_p"] = 0.98
        #tool_call_kwargs["top_k"] = 400
        step["min_p"] = 0.005
        step["jinja_args"] = { "reply_as": "assistant" }

class CriticalMode:
    def get_tools(agent, session, step):
        return [
            criticize,
            refusal
        ]

    def get_template(agent, session, step):
        return load_chatlog(_chatlogs / "critic.cl").critical_ctx

    def prepare(agent, session, step):
        session.temperature = 0.8
        step["jinja_args"] = { "reply_as": "critic" }

class ArchivistMode:
    def get_tools(agent, session, step):
        tools = [
            continue_to_think,
            rewrite_document,
            close_document,
            new_document,
            share_document,
            #save_or_load,
            #move_file,
            #delete_file,
            #create_file,
            run_program,
            finish_work,
            refusal
        ]
        if len(session.thoughts) > 1:
            tools.append(launch_archivist)
            tools.append(launch_writer)
            tools.append(launch_worker)
        if len(session.thoughts) > 2:
            tools.append(refine_log)
        if any(c.finished is None for c in session.commands.values()):
            tools.append(send_input)
            tools.append(interrupt_command)
            tools.append(wait_for_command)
            tools.append(kill_command)
        if len(session.commands) > 0:
            tools.append(discard_command)
        return tools

    def get_template(agent, session, step):
        return load_chatlog(_chatlogs / "archivist.cl").archivist_ctx

    def prepare(agent, session, step):
        session.temperature = 0.7
        step["jinja_args"] = { "reply_as": "archivist" }


class WriterMode:
    def get_tools(agent, session, step):
        tools = [
            continue_to_think,
            rewrite_document,
            new_document,
            launch_archivist,
            launch_worker,
            think_creatively,
            finish_work,
            refusal
        ]
        if len(session.thoughts) > 2:
            tools.append(refine_log)
        return tools

    def get_template(agent, session, step):
        return load_chatlog(_chatlogs / "writer.cl").writer_ctx

    def prepare(agent, session, step):
        session.temperature = 1.0
        step["jinja_args"] = { "reply_as": "writer" }

