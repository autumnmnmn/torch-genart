
from pyt.core.commands.commands import registrar_attr

_builtins = []
_builtin = registrar_attr(_builtins)

def register_builtins(group):
    group += _builtins


# TODO get from session
#API = "http://localhost:1312"
API = "https://openrouter.ai/api"
#MODEL = "locus"
MODEL = "deepseek/deepseek-v4-flash-0731"

from pyt.core.llm import chatlog
from pyt.core.llm.tools import tool, toolprop, tool_call

@tool
class complete_answer:
    """Provide a complete explanation of the issue at hand."""
    answer: str = toolprop(desc="Complete explanation of the bug.")
    confidence: float = toolprop(desc="From 0 to 1, how confident are you in your answer?")
    tldr: str = toolprop(desc="\"tl;dr\": a concise version of your explanation, for users that have brevity mode activated. just enough to get the problem solved. ok to include a few lines of code.")

@tool
class need_file:
    """Express that in order to reason about the bug, you need to load a particular file from the call stack into your working memory."""
    file_index: int
    purpose: str = toolprop(desc="An explanation of what you hope to learn by looking at that file.")

@tool
class take_notes:
    """Take notes about the issue. This is a good option if you're not totally sure what's causing the issue or how to make progress, but not ready to give up. Also good to call this before switching to another file if there's anything in the current file you think is relevant."""
    notes: str

@tool
class give_up:
    """Give up on solving the issue. Use this if you find yourself stuck in a loop or are confident you are not equipped to solve the problem."""
    partial_explanation: str = toolprop(desc="Your best effort at explaining what you *could* discern.")


class Record:
    def __init__(self, data):
        self._data = data

    @property
    def value(self):
        return self._data["val"] // self._data.get("scale", 1)

def normalize(records):
    total = sum(r.value for r in records)
    return [r.value / total for r in records]

def badfunc():
    try:
        records = [Record({"val": i, "scale": 10}) for i in range(5)]
        result = normalize(records)
    except ZeroDivisionError as e:
        raise RuntimeError("record processing pipeline failed") from e

@_builtin("debug_agent", "debug", "why", "wtf", "what")
def test_debug_agent(session, args):
    import json

    from pathlib import Path
    from pprint import pformat

    from pyt.core import AttrDict, extra_exception_data


    clfile = Path(__file__).parent.parent / "llm/prompts/debug_agent.cl"

    cl = chatlog.load_chatlog(clfile)

    if session.last_exception is None:
        session.log("No exception to debug :)")
        return

    e = session.last_exception

    import sys
    import traceback
    exc_type, exc_val, exc_tb = (type(e), e, e.__traceback__)
    frames = traceback.extract_tb(exc_tb)

    filtered_frames = [f for f in frames if not f.filename.startswith("<")]

    filenames = list(dict.fromkeys(frame.filename for frame in filtered_frames))

    extras = extra_exception_data(exc_val)

    def index_note(filename):
        if filename in filenames:
            return f"(file {filenames.index(filename)})"
        return ""

    if "filename" in extras:
        fn = extras["filename"]
        if fn not in filenames:
            filenames.append(fn)
            extras["filename"] += f" {index_note(fn)}"

    extra = "" if len(extras) == 0 else f"Exception data:\n{pformat(extras)}"

    trace_data = "\n".join([
        f"{exc_type.__name__}: {exc_val}",
        extra,
        *[
            f'in {frame.filename} {index_note(frame.filename)} line {frame.lineno}, in {frame.name}: `{frame.line}`'
            for frame in frames
        ]
    ])

    done = False

    notes = []

    file_name = "[no file]"
    file_content = ""

    session.log("Launching the debugger agent", mode="info")

    import textwrap
    _wrap = lambda text: textwrap.fill(text, width=90).replace("\n", "\n    ")

    while not done:

        subs = {
            "trace_info": trace_data,
            "notes": "\n".join(notes),
            "file_name": file_name,
            "file_content": file_content
        }

        main = chatlog.apply_substitutions(cl.main, subs)

        for m in main:
            session.log(m)

        response = tool_call(API, MODEL,
            main,
            [
                complete_answer.tool,
                need_file.tool,
                take_notes.tool,
                give_up.tool
            ],
            temperature=0.5,
            top_k=50000,
            top_p=1.0,
            min_p=0.001
        )
        call = response["choices"][0]["message"]["tool_calls"][0]["function"]

        args = AttrDict(json.loads(call["arguments"]))
        func = call["name"]

        #session.log(func)
        #session.log(args)

        match func:
            case "complete answer":
                if args.confidence < 0.95:
                    notes.append(f"I think I have the answer, but my confidence was below the certainty threshold. Here's what I'm considering: {args.answer}")
                    session.log("taking notes, refining a low-confidence answer...", mode="info")
                else:
                    #session.log(args.answer)
                    session.log.blank().log(_wrap(args.tldr))
                    done = True
            case "give up":
                session.log("Unable to produce a complete answer with high-confidence; Partial answer:", mode="warning")
                session.log(_wrap(args.partial_explanation), mode="info")
                done = True
            case "need file":
                if 0 <= args.file_index < len(filenames):
                    old_file_name = file_name
                    file_name = filenames[args.file_index]
                    if old_file_name == file_name:
                        session.log("tried to open the file that's already open...")
                        notes.append(f"I tried to open a file, but it was the one I'm already looking at. What a silly mistake!")
                    try:
                        file_path = Path(file_name)
                    except:
                        file_path = None
                        session.log(f"Tried to open a file but it didn't work: {file_name}", mode="error")
                        notes.append(f"Tried to open a file but it didn't work: {file_name}")
                    try:
                        if file_path is not None and file_path.exists():
                            with open(file_name, 'r') as f:
                                file_content = f.read()
                                session.log(f"reading a file... ({file_name})", mode="info")
                                notes.append(f"Opened file {args.file_index}, {file_name}. {args.purpose}")
                    except:
                        session.log(f"Tried to open a file but it didn't work: {file_name}", mode="error")
                        notes.append(f"Tried to open a file but it didn't work: {file_name}")
                        raise
                else:
                    notes.append(f"Tried to read a file at an invalid index: {args.file_index}")
                    session.log(f"Tried to read a file at an invalid index: {args.file_index}")
            case "take notes":
                notes.append(args.notes)
                session.log(f"taking notes about the issue...", mode="info")
            case _:
                notes.append(f"Tried to call the tool `{func}`, for which no handler has been implemented")
                session.log(f"bad tool call: {func}", mode="error")


