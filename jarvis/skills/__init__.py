"""Skill system.

A skill is a small function Jarvis can run. Each skill has:
- regex patterns, so a plain command like "what time is it" works without any AI, and
- a JSON-schema description, so the AI model can call it as a "tool".

Add a skill by writing a function in any module of this package and decorating it
with @skill(...). Named regex groups become the function's arguments.
"""

from __future__ import annotations

import importlib
import pkgutil
import re
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Context:
    """Things a skill may need: settings, memory, and a way to talk later."""

    config: Any
    memory: Any
    notify: Callable[[str], None] = print
    state: dict = field(default_factory=dict)


@dataclass
class Skill:
    name: str
    description: str
    func: Callable[..., str]
    patterns: list[re.Pattern] = field(default_factory=list)
    params: dict[str, str] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)

    def tool_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {k: {"type": "string", "description": v} for k, v in self.params.items()},
                    "required": self.required,
                },
            },
        }


_SKILLS: dict[str, Skill] = {}


def skill(name: str, description: str, patterns: list[str] | None = None,
          params: dict[str, str] | None = None, required: list[str] | None = None):
    """Register a function as a skill. The function is called as func(ctx, **args)."""

    def wrap(func):
        _SKILLS[name] = Skill(
            name=name,
            description=description,
            func=func,
            patterns=[re.compile(p, re.IGNORECASE) for p in (patterns or [])],
            params=params or {},
            required=required or [],
        )
        return func

    return wrap


class Registry:
    def __init__(self):
        for mod in pkgutil.iter_modules(__path__):
            importlib.import_module(f"{__name__}.{mod.name}")
        self.skills = dict(_SKILLS)

    def match(self, text: str) -> tuple[Skill, dict[str, str]] | None:
        text = text.strip().rstrip(".!?")
        for s in self.skills.values():
            for p in s.patterns:
                m = p.fullmatch(text)
                if m:
                    args = {k: v.strip() for k, v in m.groupdict().items() if v}
                    return s, args
        return None

    def run(self, name: str, ctx: Context, args: dict[str, Any] | None = None) -> str:
        s = self.skills.get(name)
        if s is None:
            return f"I don't have a skill called {name}."
        args = {k: v for k, v in (args or {}).items() if k in s.params}
        try:
            return str(s.func(ctx, **args))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return f"I can't reach the internet right now, so the {name} skill didn't work."
        except Exception as e:  # a broken skill must not crash Jarvis
            return f"Sorry, the {name} skill failed: {e}"

    def tool_schemas(self) -> list[dict]:
        return [s.tool_schema() for s in self.skills.values()]
