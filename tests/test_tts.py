from unittest import mock

from jarvis import tts


def test_say_speaks_text():
    fake = mock.MagicMock()
    fake.getProperty.return_value = []
    with mock.patch.object(tts, "pyttsx3") as p:
        p.init.return_value = fake
        tts.say("hello")
    fake.say.assert_called_once_with("hello")
    fake.runAndWait.assert_called_once()


def test_say_skips_empty():
    with mock.patch.object(tts, "pyttsx3") as p:
        tts.say("   ")
    p.init.assert_not_called()


def test_say_never_raises():
    with mock.patch.object(tts, "pyttsx3") as p:
        p.init.side_effect = RuntimeError("no audio")
        tts.say("hi")  # must not crash


def test_say_without_pyttsx3(capsys):
    with mock.patch.object(tts, "pyttsx3", None):
        tts.say("hi")
    assert "Jarvis: hi" in capsys.readouterr().out


def test_say_from_many_threads_uses_one_worker():
    import threading

    seen = set()
    fake = mock.MagicMock()
    fake.getProperty.return_value = []
    fake.runAndWait.side_effect = lambda: seen.add(threading.current_thread().name)
    with mock.patch.object(tts, "pyttsx3") as p:
        p.init.return_value = fake
        ts = [threading.Thread(target=tts.say, args=(f"t{i}",)) for i in range(5)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        tts.say("main")
    assert seen == {"jarvis-tts"} and fake.say.call_count == 6
