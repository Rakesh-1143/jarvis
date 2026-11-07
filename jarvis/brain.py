"""The AI "brain": talks to a free LLM (local Ollama or any OpenAI-compatible server).

The model can call Jarvis skills as tools. Example: "Should I take an umbrella in Paris?"
-> the model calls get_weather(city="Paris") -> reads the result -> answers.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error

from . import net

SYSTEM_PROMPT = """You are {name}, a helpful, witty personal AI assistant, like J.A.R.V.I.S. from Iron Man.
You are talking to {user}. Your replies are spoken aloud, so keep them short (1-3 sentences),
natural, and without markdown, lists, emojis or code unless asked.
Current date and time: {now}.
Use the provided tools when they help (weather, news, search, notes, reminders, opening apps, etc.).
Never invent tool results.{facts}"""


class BrainError(RuntimeError):
    pass


class Brain:
    def __init__(self, config, registry=None):
        self.cfg = config["llm"]
        self.assistant_cfg = config["assistant"]
        self.registry = registry
        self.provider = self.cfg["provider"].lower()

    @property
    def enabled(self) -> bool:
        return self.provider not in ("none", "off", "")

    def system_prompt(self, facts: list[str]) -> str:
        fact_txt = ("\nThings you remember about the user: " + "; ".join(facts) + ".") if facts else ""
        return SYSTEM_PROMPT.format(
            name=self.assistant_cfg["name"], user=self.assistant_cfg["user_name"],
            now=dt.datetime.now().strftime("%A %d %B %Y, %I:%M %p"), facts=fact_txt,
        )

    # ---------- providers ----------
    def _call(self, messages: list[dict], tools: list[dict] | None) -> dict:
        """Return one assistant message: {"content": str, "tool_calls": [...]}"""
        timeout = self.cfg.get("timeout", 120)
        try:
            if self.provider == "ollama":
                body = {"model": self.cfg["model"], "messages": messages, "stream": False,
                        "options": {"temperature": self.cfg["temperature"]}}
                if tools:
                    body["tools"] = tools
                data = net.post_json(self.cfg["base_url"].rstrip("/") + "/api/chat", body, timeout)
                return data["message"]
            if self.provider == "openai":
                key = os.environ.get(self.cfg["api_key_env"], "")
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                body = {"model": self.cfg["model"], "messages": messages, "temperature": self.cfg["temperature"]}
                if tools:
                    body["tools"] = tools
                data = net.post_json(self.cfg["base_url"].rstrip("/") + "/chat/completions", body, timeout, headers)
                return data["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            raise BrainError(f"AI server error {e.code}: {detail}") from e
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise BrainError(f"Can't reach the AI server at {self.cfg['base_url']} ({e}).") from e
        raise BrainError(f"Unknown LLM provider '{self.provider}'.")

    # ---------- main entry ----------
    def chat(self, text: str, history: list[dict], facts: list[str], ctx=None, max_steps: int = 4) -> str:
        messages = [{"role": "system", "content": self.system_prompt(facts)}, *history, {"role": "user", "content": text}]
        tools = self.registry.tool_schemas() if (self.registry and self.cfg.get("use_tools") and ctx) else None

        for _ in range(max_steps):
            try:
                msg = self._call(messages, tools)
            except BrainError as e:
                # Some models do not support tools; retry once without them.
                if tools and ("tool" in str(e).lower() or "does not support" in str(e).lower()):
                    tools = None
                    continue
                raise
            calls = msg.get("tool_calls") or []
            if not calls:
                return (msg.get("content") or "").strip()
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        args = {}
                result = self.registry.run(fn.get("name", ""), ctx, args)
                reply = {"role": "tool", "content": result}
                if call.get("id"):
                    reply["tool_call_id"] = call["id"]
                if self.provider == "ollama":
                    reply["tool_name"] = fn.get("name", "")
                messages.append(reply)
        return "Sorry, I got stuck thinking about that."
