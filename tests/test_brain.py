from jarvis import brain as brain_mod


def test_tool_calling_loop(jarvis, monkeypatch):
    jarvis.config.data["llm"]["provider"] = "ollama"
    jarvis.brain = brain_mod.Brain(jarvis.config, jarvis.registry)
    calls = []

    def fake_post(url, body, timeout=120, headers=None):
        calls.append(body)
        if len(calls) == 1:
            assert any(t["function"]["name"] == "calculate" for t in body["tools"])
            return {"message": {"content": "", "tool_calls": [
                {"function": {"name": "calculate", "arguments": {"expression": "6 * 7"}}}]}}
        assert body["messages"][-1] == {"role": "tool", "content": "The answer is 42.", "tool_name": "calculate"}
        return {"message": {"content": "Six times seven is 42, sir."}}

    monkeypatch.setattr(brain_mod.net, "post_json", fake_post)
    assert jarvis.handle("how much is six times seven, roughly") == "Six times seven is 42, sir."
    assert len(calls) == 2
    # the conversation is saved for context
    assert jarvis.memory.recent_messages(10)[-1]["content"] == "Six times seven is 42, sir."


def test_openai_provider(jarvis, monkeypatch):
    jarvis.config.data["llm"].update(provider="openai", base_url="https://api.groq.com/openai/v1")
    jarvis.brain = brain_mod.Brain(jarvis.config, jarvis.registry)

    def fake_post(url, body, timeout=120, headers=None):
        assert url == "https://api.groq.com/openai/v1/chat/completions"
        return {"choices": [{"message": {"content": "Hello!"}}]}

    monkeypatch.setattr(brain_mod.net, "post_json", fake_post)
    assert jarvis.handle("why is the sky blue") == "Hello!"


def test_offline_brain_message(jarvis):
    jarvis.config.data["llm"].update(provider="ollama", base_url="http://127.0.0.1:9")
    jarvis.brain = brain_mod.Brain(jarvis.config, jarvis.registry)
    assert "offline" in jarvis.handle("why is the sky blue")
