
import os
import re
import shutil

from contextlib import contextmanager
from typing import Literal, Optional
from pathlib import Path

from pyt.core.llm.tools import tool, toolprop
from pyt.core.llm.tools.images import image_content_entry

AGENT_HOME = Path("/data/2/agents")

@contextmanager
def preserve_permissions():
    old_umask = os.umask(0o007)
    try:
        yield
    finally:
        os.umask(old_umask)

def valid_name(name):
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^\w\-.]', '', name)
    return name

def agent_home(agent):
    raise Exception("deprecated!!")
    return AGENT_HOME / valid_name(agent)

def agent_resolve(agent: str, filename: str) -> Path:
    home = agent_home(agent).resolve()
    path = Path(filename)
    if path.is_absolute():
        resolved = path.resolve()
        if not resolved.is_relative_to(home):
            # treat as agent-rooted, re-root under home
            resolved = (home / path.relative_to("/")).resolve()
    else:
        resolved = (home / path).resolve()
    if not resolved.is_relative_to(home):
        raise ValueError(f"path traversal detected: {filename!r}")
    return resolved

def agent_write(agent, filename, content):
    target = agent_resolve(agent, filename)
    with preserve_permissions():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

def agent_read(agent, filename):
    path = agent_resolve(agent, filename)
    if not path.exists():
        raise FileNotFoundError()
    return path.read_text()

def agent_delete(agent, filename):
    target = agent_resolve(agent, filename)
    if not target.exists():
        raise FileNotFoundError(f"no file at {filename!r}")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()

def agent_create_file(agent, path):
    target = agent_resolve(agent, path)
    if target.exists():
        raise FileExistsError(f"file already exists at {path!r}")
    with preserve_permissions():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("")

def agent_create_directory(agent, path):
    target = agent_resolve(agent, path)
    if target.exists():
        raise FileExistsError(f"directory already exists at {path!r}")
    with preserve_permissions():
        target.mkdir(parents=True)

def agent_tree(agent):
    home = agent_home(agent)
    if not home.exists():
        return "(empty)"
    lines = []
    for path in sorted(home.rglob("*")):
        depth = len(path.relative_to(home).parts) - 1
        if depth < 3:
            prefix = "    " * depth + ("-> " if depth > 0 else "")
            lines.append(prefix + "`" + path.name + ("/` (directory)" if path.is_dir() else "` (file)"))
    return "\n".join(lines)

class Document:
    def __init__(self, name, agent, path=None):
        self.name = name
        self.agent = agent
        self.path = path
        self.dirty = False
        self.provenance = ""
        self.content = ""
        self.load()

    def load(self, path=None):
        """Load content from disk into memory. Clears dirty flag."""
        self.dirty = False
        self.path = path or self.path
        if self.path is None:
            self.content = ""
            self.provenance = "new"
            return
        if self.path.startswith("note"):
            self.content = ""
            self.provenance = self.path
            self.dirty = True
            return
        try:
            self.content = agent_read(self.agent, self.path)
            self.provenance = f"loaded from {self.path!r}"
        except FileNotFoundError:
            self.content = ""
            self.provenance = f"new at {self.path!r}"
            self.dirty = True
        except IsADirectoryError:
            self.content = "[ERROR]"
            self.provenance = f"failed to load ({self.path!r} is a directory)"
            self.dirty = False
            return

    def share(self, sharer):
        copy = Document(self.name, self.agent, self.path)
        copy.provenance = f"note from {sharer}"
        copy.content = self.content
        return copy

    def rewrite(self, content):
        """Replace in-memory content. Does not touch disk."""
        self.content = content
        self.dirty = True

    def save(self, path=None):
        """Flush in-memory content to disk."""
        self.path = path or self.path or self.name
        agent_write(self.agent, self.path, self.content)
        self.dirty = False

    def __str__(self):
        status = "unarchived changes" if self.dirty else "no changes"
        return (
            f"[document: {self.name!r} | {self.provenance} | {status}]\n"
            f"```\n{self.content}\n```\n[end of {self.name!r}]"
        )



@tool
class move_file:
    """Move a file in your directory. Has no effect on documents already loaded from that file."""
    from_path: str = toolprop(desc="The current location of the file")
    to_path: str = toolprop(desc="The location where you want the file to be")

    def handler(agent, session, args):
        src = agent_resolve(agent.name, args.from_path)
        dst = agent_resolve(agent.name, args.to_path)
        if not src.exists():
            print(f"move failed: no file at {args.from_path!r}")
            session.thoughts.append(f"Tried to move {args.from_path!r} but it doesn't exist")
            return
        with preserve_permissions():
            dst.parent.mkdir(parents=True, exist_ok=True)
            src.rename(dst)
        print(f"moved {args.from_path!r} -> {args.to_path!r}")
        session.thoughts.append(f"Moved {args.from_path!r} to {args.to_path!r}")

@tool
class delete_file:
    """Delete a file or subdirectory from your directory. Has no effect on documents already loaded from that file."""
    path: str

    def handler(agent, session, args):
        try:
            agent_delete(agent.name, args.path)
            print(f"deleted {args.path!r}")
            session.thoughts.append(f"Deleted file {args.path!r}")
        except (ValueError, FileNotFoundError) as e:
            print(f"delete failed: {e}")
            session.thoughts.append(f"Tried to delete a file but it failed: {e}")

@tool
class create_file:
    """Create a file or directory"""
    path: str
    create_as: Literal["file", "directory"]

    def handler(agent, session, args):
        try:
            if args.create_as == "directory":
                agent_create_directory(agent.name, args.path)
            else:
                agent_create_file(agent.name, args.path)
            print(f"created {args.create_as} {args.path!r}")
            session.thoughts.append(f"Created {args.create_as} {args.path!r}")
        except (ValueError, FileExistsError) as e:
            print(f"create failed: {e}")
            session.thoughts.append(f"Tried to create {args.create_as} {args.path!r} but it failed: {e}")

@tool
class update_self:
    """This tool lets you modify yourself. You can change what your goals are, adjust your style notes, or even change your name and rewrite your entire description of who you are."""
    attribute: Literal["self", "goals", "style", "name"]
    new_value: str = toolprop(desc="The attribute of yourself that you select will be replaced with what you write here.")
    thought: str = toolprop(desc="An entry to your thoughts list to describe the change you made.")

    def handler(agent, session, args):
        session.thoughts.append("Made a self-modification: " + args.thought)
        agent[args.attribute] = args.new_value
        return
        #if args.attribute in ["self", "goals", "style"]:
        #    file_name = f"{args.attribute}.md"
        #    agent_write(agent.name, file_name, args.new_value)
        #    for file in session.files.values():
        #        if file.path == file_name:
        #            file.content = args.new_value
        #            file.dirty = False

@tool
class new_document:
    """Create a new document"""
    document_name: str
    content: str

    def handler(agent, session, args):
        session.files[args.document_name] = Document(args.document_name, agent.name, None)
        session.files[args.document_name].content = args.content
        session.thoughts.append(f"Created a new document {args.document_name!r}")

@tool
class new_note:
    """Create a new note"""
    note_name: str
    content: str

    def handler(agent, session, args):
        session.files[args.note_name] = Document(args.note_name, agent.name, "note")
        session.files[args.note_name].content = args.content
        session.thoughts.append(f"Created a new note {args.note_name!r}")

@tool
class rewrite_note:
    """Rewrite one of the open notes"""
    note_name: str = toolprop(desc="The name of the note")
    content: str = toolprop(desc="The new content")

    def handler(agent, session, args):
        f = session.files.get(args.note_name)
        if f is None:
            new_note.handler(agent, session, args)
        else:
            f.rewrite(args.content)
            print(f"rewrote note {args.note_name!r}")
            session.thoughts.append(f"Rewrote {args.note_name!r}")

@tool
class close_note:
    """Close one of the open notes."""
    note_name: str

    def handler(agent, session, args):
        f = session.files.get(args.note_name)
        if f is None:
            print(f"close failed: no open note named {args.note_name!r}")
        else:
            if f.dirty:
                print(f"closed file {args.note_name!r} (discarded unsaved changes!)")
            else:
                print(f"closed file {args.note_name!r}")
            del session.files[args.note_name]
            session.thoughts.append(f"Closed note {args.note_name!r}")

@tool
class rewrite_document:
    """Rewrite one of the open documents"""
    document_name: str = toolprop(desc="The name of the document")
    content: str = toolprop(desc="The new content")

    def handler(agent, session, args):
        f = session.files.get(args.document_name)
        if f is None:
            new_document.handler(agent, session, args)
        else:
            f.rewrite(args.content)
            print(f"rewrote document {args.document_name!r}")
            session.thoughts.append(f"Rewrote {args.document_name!r}")

@tool
class share_document:
    """Make a document available to the user that assigned you your task."""
    document_name: str

    def handler(agent, session, args):
        f = session.files.get(args.document_name)
        if f is None:
            pass
        else:
            session.parent.files[args.document_name] = f.share("archivist")
            session.thoughts.append(f"Shared {args.document_name} with my task-giver.")

@tool
class share_note:
    """Make a note available to the user that assigned you your task."""
    note_name: str

    def handler(agent, session, args):
        f = session.files.get(args.note_name)
        if f is None:
            pass
        else:
            session.parent.files[args.note_name] = f.share("worker")
            session.thoughts.append(f"Shared {args.note_name} with my task-giver.")

@tool
class close_document:
    """Close one of the open documents. Unsaved changes will be lost."""
    document_name: str

    def handler(agent, session, args):
        f = session.files.get(args.document_name)
        if f is None:
            print(f"close failed: no open file named {args.document_name!r}")
        else:
            if f.dirty:
                print(f"closed file {args.document_name!r} (discarded unsaved changes!)")
            else:
                print(f"closed file {args.document_name!r}")
            del session.files[args.document_name]
            session.thoughts.append(f"Closed {args.document_name!r}")

@tool
class view_image:
    """Load an image from a file in your personal directory."""
    file_path: str = toolprop(desc="Path to the image file, relative to your root directory")
    scale: Literal["thumbnail", "full"]

    def handler(agent, session, args):
        try:
            path = agent_resolve(agent.name, args.file_path)

            if not path.exists():
                raise FileNotFoundError(f"no file at {args.file_path!r}")

            if not hasattr(session, "images"):
                session.images = []
            if not hasattr(session, "image_sources"):
                session.image_sources = []

            image_index = len(session.image_sources)

            imagemagick_args = None
            if args.scale == "thumbnail":
                imagemagick_args = ["-resize", "512x512>"]

            block = image_content_entry(
                path,
                imagemagick_args=imagemagick_args,
                output_format="png",
            )

            source = f"{agent.name}:{args.file_path}:{args.scale}"

            descriptor = f"[image {image_index}: source={source}]"

            session.images.append(descriptor)
            session.images.append(block)

            session.image_sources.append(source)

            print(f"loaded image {args.file_path!r} ({args.scale}) as index {image_index}")
            session.thoughts.append(f"Loaded image {args.file_path!r} ({args.scale})")

        except Exception as e:
            print(f"view_image failed: {e}")
            session.thoughts.append(f"Failed to view image {args.file_path!r}: {e}")

@tool
class discard_image:
    """Remove an image from the context."""
    index: int = toolprop(desc="Logical image index (0-based)")

    def handler(agent, session, args):
        try:
            if not hasattr(session, "images") or not hasattr(session, "image_sources"):
                print("discard failed: no images loaded")
                return

            i = args.index

            if i < 0 or i >= len(session.image_sources):
                raise IndexError(f"index {i} out of range")

            text_idx = 2 * i
            image_idx = text_idx + 1

            removed_source = session.image_sources[i]

            # Remove in reverse order
            del session.images[image_idx]
            del session.images[text_idx]
            del session.image_sources[i]

            print(f"discarded image at index {i}")
            session.thoughts.append(f"Discarded image {removed_source}")

        except Exception as e:
            print(f"discard failed: {e}")
            session.thoughts.append(f"Failed to discard image: {e}")

@tool
class save_or_load:
    """Save/load text documents to/from files in your personal directory. You can have more than one copy of the same file open at a time, as separate documents, for example if you want to keep un unmodified copy of a file open while you make changes to it in another document. The file_path is the path of the file on disk, while document_name is what you are calling the open copy in your working memory.
    Operations:
    `load`: Load the contents of the file at `file_path` into the document `document_name`, overwriting any previous document contents. If no file is found at that path, this will open a fresh new document.
    `save`: Saves the contents of the document `document_name` into the file `file_path`, overwriting any previous file contents.
    """
    file_path: str = toolprop(desc="The path of the file on disk, *relative to your root directory*. If your path is relative to a subdirectory, you will get the wrong file!")
    document_name: str = toolprop(desc="The name of the document in your memory.")
    operation: Literal["load", "save"]

    def handler(agent, session, args):
        op = args.operation
        document_name = args.document_name
        file_path = args.get("file_path")

        if op == "load":
            if document_name in session.files:
                session.files[document_name].load(file_path)
                print(f"reloaded document {document_name!r}")
            else:
                session.files[document_name] = Document(document_name, agent.name, path=file_path)
                print(f"opened file {document_name!r}")
            session.thoughts.append(f"Loaded {file_path!r} into {document_name!r}")

        elif op == "save":
            f = session.files.get(document_name)
            if f is None:
                print(f"save failed: no open document named {document_name!r}")
            else:
                try:
                    f.save(file_path)
                    if file_path in ["self.md", "goals.md", "style.md"]:
                        session[file_path[:-3]] = f.content
                    print(f"saved file {document_name!r} -> {f.path!r}")
                    session.thoughts.append(f"Saved {document_name!r} as {f.path!r}")
                except FileExistsError as e:
                    session.thoughts.append(f"Tried to save {document_name!r} as {f.path!r} but one of the directories that'd create is already a file!")


