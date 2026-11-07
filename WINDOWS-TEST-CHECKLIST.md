# Test Jarvis on your Windows PC (about 15 minutes)

Do these in order. If a step fails, send me the message on screen, plus `jarvis.log`,
`jarvis-crash.log` and `doctor-report.txt` from the jarvis folder.

## 1. Install
- [ ] Copy the `jarvis` folder to `C:\jarvis` (not the Desktop, not OneDrive).
- [ ] Double-click `packaging\install.bat`. It should end with "Done!".
      (If one optional package fails, it still finishes and lists it. That's OK.)
- [ ] Settings > Privacy & security > Microphone: "Let desktop apps access your microphone" is ON.

## 2. Self-check
Open a Command Prompt in `C:\jarvis` and run:
```
.venv\Scripts\python main.py --doctor
```
- [ ] Packages, Config, Speech model, Microphone, Voice are all **OK**.

## 3. Text mode (no mic needed)
```
.venv\Scripts\python main.py --text
```
- [ ] First time it asks setup questions (name, city...). Answer them.
- [ ] `what time is it` (you should **hear** the answer too)
- [ ] `open notepad`, then `close notepad`
- [ ] `open whatsapp` or `open zoom` (any Store app you have)
- [ ] `set volume to 30`, then `mute`, `unmute`
- [ ] `brightness 50` (laptops; many desktop monitors can't)
- [ ] `take a screenshot` (saved in Pictures\Jarvis)
- [ ] `set a timer for 10 seconds` (you should hear it go off)
- [ ] `weather` (needs internet)
- [ ] `goodbye`

## 4. Voice mode
```
.venv\Scripts\python main.py
```
- [ ] Say **"Jarvis"**. You hear a short beep.
- [ ] Say **"what time is it"**. It answers out loud.
- [ ] Right after the answer, say **"open calculator"** without "Jarvis" (follow-up mode).
- [ ] A Jarvis icon shows in the system tray (bottom right).
- [ ] Say **"Jarvis" … "goodbye"**. It stops.

## 5. Auto-start
- [ ] If you said Yes to auto-start: sign out and sign in. Within a minute, say "Jarvis". It answers.
- [ ] Start `main.py` again by hand while that one runs. It must say **"Jarvis is already running"** (no double answers).

## 6. Optional (only if you use them)
- [ ] AI: put your Claude key in `config.yaml` (`ai: api_key:`), then ask "who wrote Harry Potter".
- [ ] "Wi-Fi off" / "Bluetooth on" (asks you to confirm Wi-Fi off).
- [ ] "What's playing" while Spotify/YouTube plays.
- [ ] "Read the screen" (Windows OCR).
- [ ] "Read my notifications" (Windows may ask for permission the first time).
- [ ] "Do I have meetings today" (Outlook desktop / calendar link in config).
