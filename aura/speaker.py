"""Offline text-to-speech for AURA (nothing leaves the PC).

HISTORY OF THIS FILE (why it looks the way it does):
- v0.1.0: pyttsx3 engine created on the main thread, spoken from fresh
  worker threads. Speech died after the first utterance (COM objects
  must only be touched from their creating thread).
- v0.1.1: engine moved onto one dedicated thread, spoken via a queue.
  Still went silent after the first line.
- v0.1.2: added engine.stop() reset + engine rebuild on failure, plus
  a speech log. The log then proved the app hears and answers every
  turn — pyttsx3 reported "SPEAK OK" for every utterance — yet only
  the first one was audible. pyttsx3/SAPI5 can silently produce no
  sound while returning success, so no pyttsx3-side fix can detect it.
- v0.1.3 (current): on Windows, speech goes through the built-in
  System.Speech engine via a fresh PowerShell process per utterance.
  No reused engine, no leftover state to go silent. pyttsx3 remains
  only as a fallback (and for non-Windows).
- FIX (2026-10-26): the PowerShell helper window is now hidden
  (CREATE_NO_WINDOW). Without it, Windows popped a visible window
  up for every utterance — it appeared while AURA talked and
  vanished when the sentence ended.
- Phase 5 (barge-in): the speaker is interruptible. ``stop()`` kills
  the speech process (or stops the fallback engine) so the user can
  cut AURA off mid-sentence, from the mic button or by saying the
  wake word while it talks. A stop when nothing is playing is a
  harmless no-op, and the stop flag is cleared when the next
  utterance starts, so a stray stop never silences later speech.

System.Speech is part of Windows itself — no download, no internet.
"""

import os
import platform
import queue
import subprocess
import threading

_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aura-speech.log",
)


def _log(line: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def _run_hidden_ps(script: str):
    """Run a PowerShell script with no window. Returns (rc, out, err)."""
    startupinfo = None
    creationflags = 0
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creationflags = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=30,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def has_hindi_voice() -> bool:
    """True if a Hindi (hi-IN) voice is installed on this PC.

    Phase 7: switching to Hindi is only allowed when a Hindi voice
    exists — otherwise Hindi text would be read by an English voice.
    Installing one is a Windows Settings step (language pack /
    speech voice), not something AURA can do itself.
    """
    if platform.system() != "Windows":
        return False
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "($s.GetInstalledVoices() | Where-Object { "
        "$_.VoiceInfo.Culture.Name -eq 'hi-IN' }).Count"
    )
    try:
        rc, out, _ = _run_hidden_ps(script)
        if rc == 0 and int(out) > 0:
            return True
    except Exception:  # noqa: BLE001 - fall through to the WinRT check
        pass
    # Phase 7 voice fix: also accept a WinRT (OneCore) Hindi or
    # Indian English voice, which is how Settings-installed voices
    # are registered. A registry-copied SAPI token may enumerate
    # yet fail to synthesize Devanagari, so the WinRT voice is the
    # reliable one — and en-IN suffices for Hinglish replies.
    script = (
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
        "[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows, "
        "ContentType=WindowsRuntime] | Out-Null; "
        "([Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices "
        "| Where-Object { $_.Language -eq 'hi-IN' -or "
        "$_.Language -eq 'en-IN' }).Count"
    )
    try:
        rc, out, _ = _run_hidden_ps(script)
    except Exception:  # noqa: BLE001 - any failure reads as False
        return False
    if rc != 0:
        return False
    try:
        return int(out) > 0
    except ValueError:
        return False


def _powershell_script(text: str, language: str) -> str:
    """System.Speech script for ``text`` in ``language``.

    Hindi picks a hi-IN voice when one is installed; the try/catch
    keeps speech working (with the default voice) if none is found.
    """
    safe = text.replace("'", "''").replace("\r", " ").replace("\n", " ")
    voice = ""
    if language == "hi":
        voice = (
            "try { $s.SelectVoiceByCulture('hi-IN') } catch { }; "
        )
    return (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"{voice}$s.Speak('{safe}') | Out-Null"
    )


def _winrt_script(text: str, culture: str = "hi-IN") -> str:
    """WinRT speech script for ``text`` in a OneCore voice culture.

    Phase 7 voice fix: synthesize with a OneCore voice (the kind
    Settings installs), save the stream to a temp WAV, and play it
    back synchronously. The AsTask preamble mirrors the radio
    script, which already runs on Windows this way. The template
    keeps PowerShell braces literal; only __TEXT__ and __CULTURE__
    are substituted, so no brace-doubling bugs.
    """
    safe = text.replace("'", "''").replace("\r", " ").replace("\n", " ")
    template = (
        "Add-Type -AssemblyName System.Runtime.WindowsRuntime; "
        "$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | "
        "Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and "
        "$_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]; "
        "[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows, "
        "ContentType=WindowsRuntime] | Out-Null; "
        "$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer; "
        "$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices | "
        "Where-Object { $_.Language -eq '__CULTURE__' } | Select-Object -First 1; "
        "if ($null -eq $voice) { throw 'No __CULTURE__ WinRT voice' }; "
        "$synth.Voice = $voice; "
        "$op = $synth.SynthesizeTextToStreamAsync('__TEXT__'); "
        "$task = $asTaskGeneric.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($op)); "
        "$task.Wait(-1) | Out-Null; "
        "$stream = $task.Result; "
        "$tmp = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), '.wav'); "
        "$reader = New-Object Windows.Storage.Streams.DataReader($stream); "
        "$loadOp = $reader.LoadAsync([uint32]$stream.Size); "
        "$loadTask = $asTaskGeneric.MakeGenericMethod([uint32]).Invoke($null, @($loadOp)); "
        "$loadTask.Wait(-1) | Out-Null; "
        "$bytes = New-Object byte[] ([int]$stream.Size); "
        "$reader.ReadBytes($bytes); "
        "[System.IO.File]::WriteAllBytes($tmp, $bytes); "
        "$player = New-Object System.Media.SoundPlayer($tmp); "
        "$player.PlaySync(); "
        "Remove-Item $tmp -Force"
    )
    return template.replace("__TEXT__", safe).replace("__CULTURE__", culture)


class Speaker:
    def __init__(self, rate: int = 175):
        self._rate = rate
        # Phase 7: spoken language ("en" or "hi"), set by main.py
        # from the saved mode before each turn.
        self.language = "en"
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        # Barge-in state: what is speaking right now, if anything.
        self._current_proc = None
        self._current_engine = None
        self._proc_lock = threading.Lock()
        self._stop_requested = threading.Event()

    def stop(self) -> None:
        """Interrupt the utterance in progress, if any.

        Safe to call anytime — with nothing playing it just sets a
        flag the next utterance clears. Never blocks: killing the
        process (or stopping the engine) is what unblocks say().
        """
        self._stop_requested.set()
        with self._proc_lock:
            proc = self._current_proc
            engine = self._current_engine
        if proc is not None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001, S110 - already gone
                pass
        if engine is not None:
            try:
                engine.stop()
            except Exception:  # noqa: BLE001, S110 - best effort
                pass

    def _run_hidden(self, cmd) -> tuple[int, str]:
        """Run ``cmd`` with no window, tracking it for stop().

        Returns (returncode, stderr). A kill from stop() shows up as
        a negative returncode, which the caller treats as an
        interruption, not a failure.
        """
        startupinfo = None
        creationflags = 0
        if platform.system() == "Windows":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        with self._proc_lock:
            self._current_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags,
            )
            proc = self._current_proc
        try:
            _, stderr = proc.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()
            _, stderr = proc.communicate()
            raise RuntimeError("Speech process timed out")
        finally:
            with self._proc_lock:
                self._current_proc = None
        return proc.returncode, stderr.strip()

    def set_language(self, language: str) -> None:
        """Switch the spoken language for upcoming utterances."""
        if language in ("en", "hi"):
            self.language = language

    def _speak_winrt(self, text: str) -> None:
        """Speak Hindi-mode text via Windows' newer voice system (WinRT).

        Hinglish is Roman script, so an Indian English (en-IN)
        voice is tried first, then the Hindi (hi-IN) voice. Same
        hidden-process + stop-tracking shape as the SAPI path, so
        stop() still cuts playback off mid-sentence.
        """
        last_error = None
        for culture in ("en-IN", "hi-IN"):
            returncode, stderr = self._run_hidden(
                [
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    _winrt_script(text, culture),
                ]
            )
            if self._stop_requested.is_set():
                return  # interrupted by stop(): not an error
            if returncode == 0:
                return
            last_error = stderr or f"WinRT speech failed ({culture})"
        raise RuntimeError(last_error)

    def _speak_powershell(self, text: str) -> None:
        """Speak via Windows' built-in System.Speech (fresh process).

        The helper process runs with its window hidden: without
        CREATE_NO_WINDOW, Windows shows a console window for the
        PowerShell process, so a window popped up for every spoken
        reply and closed when the sentence finished."""
        returncode, stderr = self._run_hidden(
            [
                "powershell", "-NoProfile", "-NonInteractive", "-Command",
                _powershell_script(text, self.language),
            ]
        )
        if self._stop_requested.is_set():
            return  # interrupted by stop(): not an error
        if returncode != 0:
            raise RuntimeError(stderr or "PowerShell speech failed")

    def _speak_pyttsx3(self, text: str) -> None:
        """Fallback: fresh pyttsx3 engine per utterance, then discarded.

        Deliberately does NOT force a Hindi voice here: this is the
        last fallback, reached only after WinRT and SAPI failed, so
        an installed Hindi voice is likely the broken one — the
        default voice stays audible where a forced Hindi voice
        would go silent.
        """
        import pyttsx3

        engine = pyttsx3.init()
        with self._proc_lock:
            self._current_engine = engine
        try:
            engine.setProperty("rate", 175)
            engine.say(text)
            engine.runAndWait()
        finally:
            with self._proc_lock:
                self._current_engine = None
            try:
                engine.stop()
            except Exception:  # noqa: BLE001, S110 - best effort cleanup
                pass

    def _worker(self):
        while True:
            text, done = self._jobs.get()
            self._stop_requested.clear()
            try:
                if platform.system() == "Windows":
                    # Hindi tries WinRT first (the voices as
                    # installed), then SAPI, then the fallback.
                    # English keeps the proven SAPI path.
                    attempts = (
                        [
                            self._speak_winrt,
                            self._speak_powershell,
                            self._speak_pyttsx3,
                        ]
                        if self.language == "hi"
                        else [self._speak_powershell, self._speak_pyttsx3]
                    )
                    last_exc = None
                    for attempt in attempts:
                        try:
                            attempt(text)
                            last_exc = None
                            break
                        except Exception as exc:  # noqa: BLE001 - next fallback
                            _log(f"{attempt.__name__} failed ({exc!r})")
                            last_exc = exc
                    if last_exc is not None:
                        raise last_exc
                else:
                    self._speak_pyttsx3(text)
                if self._stop_requested.is_set():
                    _log(f"SPEAK INTERRUPTED: {text}")
                else:
                    _log(f"SPEAK OK: {text}")
            except Exception as exc:  # noqa: BLE001 - never kill the thread
                _log(f"SPEAK FAIL: {exc!r} (text was: {text})")
            finally:
                done.set()

    def say(self, text: str) -> None:
        """Speak ``text`` aloud, blocking until it finishes."""
        if not text:
            return
        done = threading.Event()
        self._jobs.put((text, done))
        done.wait()

    def set_rate(self, rate: int) -> None:
        self._rate = rate
