
import re
import json

from dataclasses import dataclass
from typing import List, Dict

from pyt.core import AttrDict

def chatEntry(role: str, content) -> AttrDict:
    return AttrDict({"role": role, "content": content})

class Collector:
    def __init__(self, name=None):
        self.name = name

    def collect(self, line):
        pass

    def finalize(self):
        pass

class LiteralCollector(Collector):
    def __init__(self, name):
        super().__init__(name)
        self.lines = []

    def collect(self, line):
        self.lines.append(line)

    def finalize(self):
        result = ""
        in_blank_run = False
        for line in self.lines:
            if line == "":
                in_blank_run = True
            else:
                if result:
                    result += '\n\n' if in_blank_run else ' '
                result += line
                in_blank_run = False
        return result

class ChatCollector(Collector):
    def __init__(self, name):
        super().__init__(name)
        self.chat = []
        self.current_collector = Collector()

    def collect(self, line):
        if line.startswith(".") and line.endswith(":") and len(line) > 2:
            role = line[1:-1]
            if self.current_collector.name is not None:
                self.chat.append(chatEntry(
                    self.current_collector.name,
                    self.current_collector.finalize()
                ))
            self.current_collector = LiteralCollector(role)
        else:
            self.current_collector.collect(line)

    def finalize(self):
        if self.current_collector.name is not None:
            self.chat.append(chatEntry(
                self.current_collector.name,
                self.current_collector.finalize()
            ))
        return self.chat

def apply_substitutions(source, substitutions: Dict, mode="chat"):

    if mode == "chat":
        return [
            chatEntry(apply_substitutions(entry.role, substitutions, mode="str"), apply_substitutions(entry.content, substitutions, mode="content"))
            for entry in source
        ]

    if mode == "str":
        def replacer(match):
            key = match.group(1)
            if key not in substitutions:
                return match.group(0)
            return json.dumps(substitutions[key], indent=4)
        return re.sub(r'\$\{\s*([^}]+?)\s*\}', replacer, source)

    if mode == "content":
        keys_in_source = set(re.findall(r'\$\{\s*([^}]+?)\s*\}', source))
        typed_keys = {
            k for k in keys_in_source
            if (isinstance(substitutions.get(k), dict) and "type" in substitutions.get(k, {}))
            or isinstance(substitutions.get(k), list)
        }

        if not typed_keys:
            return apply_substitutions(source, substitutions, mode="str")

        # apply only non-typed substitutions
        text_subs = {k: v for k, v in substitutions.items() if k not in typed_keys}
        intermediate = apply_substitutions(source, text_subs, mode="str")

        # ONLY split on the specific typed keys we care about
        # ignoring ${...} that happens to exist inside the injected file contents!
        key_pattern = '|'.join(re.escape(k) for k in typed_keys)
        parts = re.split(rf'\$\{{\s*({key_pattern})\s*\}}', intermediate)

        result = []
        for i, part in enumerate(parts):
            if i % 2 == 0:
                if part: # ignore empties
                    result.append({"type": "text", "text": part})
            else:
                key = part.strip()
                value = substitutions.get(key)

                if value is None:
                    print(f"Substitution error, missing {key}.")

                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and "type" in item:
                            result.append(item)
                        elif isinstance(item, str):
                            result.append({"type": "text", "text": item})
                        else:
                            raise ValueError(f"Invalid block in list for key '{key}': {item}")
                elif isinstance(value, dict) and "type" in value:
                    result.append(value)
                else:
                    # not a string, list, or dict... weird but we'll just stringify it *shrug*
                    result.append({"type": "text", "text": str(value)})

        return result

def read_chatlog(text: str) -> Dict:
    lines = text.split('\n')
    if (len(lines) < 3 or lines[0] != '' or
        not lines[1].startswith('chatlog ') or lines[2] != ''):
        raise ValueError('invalid chatlog header')

    chatlog = {}
    collector = Collector()

    for line in lines[3:]:
        if line.startswith(".chat "):
            name = line[6:]
            if collector.name is not None:
                chatlog[collector.name] = collector.finalize()
            collector = ChatCollector(name)
        elif line.startswith(".literal "):
            name = line[9:]
            if collector.name is not None:
                chatlog[collector.name] = collector.finalize()
            collector = LiteralCollector(name)
        else:
            collector.collect(line)

    if collector.name is not None:
        chatlog[collector.name] = collector.finalize()

    return chatlog

def load_chatlog(filepath: str) -> AttrDict:
    with open(filepath, 'r') as f:
        return AttrDict(read_chatlog(f.read()))

