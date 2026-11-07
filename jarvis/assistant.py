"""The Assistant: turns one line of text into one reply."""

from __future__ import annotations

import re
from typing import Callable

from .brain import Brain, BrainError
from .config import Config
from .memory import Memory
from .skills import Context, Registry
from .skills.productivity import start_scheduler

EXIT_WORDS = {"exit", "quit", "goodbye", "bye", "good bye", "stop listening", "shut up", "go to sleep jarvis"}


class Assistant:
    def __init__(self, config: Config, notify: Callable[[str], None] = print, memory: Memory | None = None):
        self.config = config
        self.name = config["assistant"]["name"]
        self.memory = memory or Memory(config.data_dir / "jarvis.db")
        self.registry = Registry()
        self.ctx = Context(config=config, memory=self.memory, notify=notify)
        self.brain = Brain(config, self.registry)
        self._scheduler = None

    def start_background(self) -> None:
        """Start the reminder checker (call once)."""
        if self._scheduler is None:
            self._scheduler = start_scheduler(self.ctx)

    def stop(self) -> None:
        self.ctx.state["stop"] = True

    def strip_wake_word(self, text: str) -> str:
        wake = re.escape(self.config["voice"]["wake_word"])
        return re.sub(rf"^\s*(hey |ok |okay |hi )?{wake}\b[\s,.:!]*", "", text, flags=re.I).strip()

    def is_exit(self, text: str) -> bool:
        return text.lower().strip(" .!") in EXIT_WORDS

    def handle(self, text: str) -> str:
        text = self.strip_wake_word(text)
        if not text:
            return "Yes?"
        if text.lower() in ("clear history", "forget this conversation", "new conversation"):
            self.memory.clear_history()
            return "Conversation cleared."

        # 1) Fast path: a built-in skill matched by pattern (no AI needed).
        hit = self.registry.match(text)
        if hit:
            skill, args = hit
            reply = self.registry.run(skill.name, self.ctx, args)
        # 2) Otherwise ask the AI brain, which may call skills as tools.
        elif self.brain.enabled:
            history = self.memory.recent_messages(self.config["llm"]["history_turns"] * 2)
            try:
                reply = self.brain.chat(text, history, self.memory.facts(), self.ctx) or "I'm not sure what to say."
            except BrainError as e:
                reply = (f"My AI brain is offline: {e} "
                         "Install Ollama from ollama.com and run 'ollama pull llama3.2', or say 'help' for built-in commands.")
                return reply
        else:
            return "I don't know that command yet. Say 'help' to hear what I can do."

        self.memory.add_message("user", text)
        self.memory.add_message("assistant", reply)
        return reply
