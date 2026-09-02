"""Entry point: wire config, injector, transcriber, recorder and hotkey together.

    python -m stt.main
"""
from __future__ import annotations

import logging
import os
import queue
import re
import signal
import socket
import threading
import time
from datetime import datetime
from pathlib import Path

from .audio import EndpointDetector, Recorder
from .cleanup import clean_text
from .config import load
from .hotkey import Listener
from .indicator import Indicator
from .inject import InjectionFailed, NoInjectorError, probe
from .power import on_power_saver
from .stats import Timings
from .textfmt import apply_format
from .transcribe import Transcriber

log = logging.getLogger("stt")


class AlreadyRunning(RuntimeError):
    pass


def single_instance_lock(name: str = "lightweight-stt") -> socket.socket:
    """Hold an abstract-namespace socket for the lifetime of the process."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        sock.bind("\0" + name)
    except OSError as exc:
        raise AlreadyRunning(f"another instance already holds {name!r}") from exc
    return sock


def history_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")
    d = Path(base) / "lightweight-stt"
    d.mkdir(parents=True, exist_ok=True)
    return d / "history.log"


_KEY_RE = re.compile(r"^<key:([a-z]+)>$", re.IGNORECASE)


def _norm(text: str) -> str:
    return text.strip().lower().rstrip(".!?").strip()


def run_command(action: str, injector) -> None:
    """`<undo>`, `<key:NAME>`, or a literal string to type (e.g. '\\n', '. ')."""
    if action == "<undo>":
        injector.undo()
        return
    m = _KEY_RE.match(action.strip())
    if m:
        injector.send_key(m.group(1))
        return
    injector.send(action)


def emit_segment(pcm, transcriber, injector, indicator, trailing_space: bool,
                 language: str | None = None, translate: bool = False,
                 record: Path | None = None, redact: bool = False,
                 quiet: bool = False, commands: dict | None = None,
                 cleaner=None, timings=None, text_format: str | None = None) -> None:
    """Transcribe one audio segment and type it. Shared by push-to-talk and the
    continuous-mode worker. `quiet` skips the indicator so the chime can't feed
    back into the mic between segments."""
    t0 = time.perf_counter()
    text = transcriber.transcribe(pcm, language=language, translate=translate)
    if timings is not None:
        dt = time.perf_counter() - t0
        timings.add(dt)
        log.info("transcribed in %d ms", dt * 1000)
    tag = f" [{language}{'→en' if translate else ''}]" if language else ""
    if text and commands:
        action = commands.get(_norm(text))
        if action is not None:
            log.info("%.1fs audio%s -> command %r", len(pcm) / 16000, tag, text)
            run_command(action, injector)
            if not quiet:
                indicator.set("ready")
            return
    if text and cleaner is not None and not redact:   # privacy: transcript stays in-process
        text = cleaner(text)
    if text and text_format:
        text = apply_format(text, text_format)
    if text:
        if redact:
            log.info("%.1fs audio%s -> %d chars", len(pcm) / 16000, tag, len(text))
        else:
            log.info("%.1fs audio%s -> %r", len(pcm) / 16000, tag, text)
        injector.send(text + (" " if trailing_space else ""))
        if record and not redact:
            with open(record, "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now().isoformat(timespec='seconds')}\t"
                         f"{language or ''}{'→en' if translate else ''}\t{text}\n")
    else:
        log.info("%.1fs audio%s -> (nothing)", len(pcm) / 16000, tag)
    if not quiet:
        indicator.set("ready")


def handle_utterance(recorder, transcriber, injector, indicator, trailing_space: bool,
                     language: str | None = None, translate: bool = False,
                     record: Path | None = None, redact: bool = False,
                     commands: dict | None = None, cleaner=None, timings=None,
                     text_format: str | None = None) -> None:
    pcm = recorder.stop()
    indicator.set("processing")
    emit_segment(pcm, transcriber, injector, indicator, trailing_space,
                 language=language, translate=translate, record=record, redact=redact,
                 commands=commands, cleaner=cleaner, timings=timings, text_format=text_format)


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = load()

    try:
        _lock = single_instance_lock()  # noqa: F841 — kept alive for the process
    except AlreadyRunning as exc:
        log.error("%s", exc)
        return 1

    try:
        injector = probe(cfg)
    except NoInjectorError as exc:
        log.error("%s", exc)
        return 1

    indicator = Indicator(cfg.indicator)
    indicator.set("processing")
    transcriber = Transcriber(
        cfg.model_dir, cfg.device, cfg.language, cfg.cache_dir, cfg.min_speech_ms,
        extra_hallucinations=cfg.hallucinations, vocabulary=cfg.vocabulary,
        num_beams=cfg.num_beams,
    )
    streaming = cfg.mode == "streaming"
    vad = EndpointDetector(min_speech_ms=cfg.min_speech_ms,
                           silence_ms=cfg.vad_silence_ms,
                           threshold=cfg.vad_threshold) if streaming else None
    recorder = Recorder(device=cfg.audio_device, vad=vad)
    indicator.set("ready")

    record = None if cfg.privacy else (history_path() if cfg.history else None)
    cleaner = None
    if cfg.llm_cleanup and cfg.privacy:
        log.info("llm cleanup off — privacy mode keeps transcripts in-process")
    elif cfg.llm_cleanup:
        cleaner = lambda t: clean_text(t, cfg.llm_endpoint, cfg.llm_model)  # noqa: E731
        log.info("llm cleanup on via %s (%s)", cfg.llm_endpoint, cfg.llm_model)
    timings = Timings() if cfg.latency_stats else None
    if timings is not None:
        log.info("latency stats on")
    st = {"lang": cfg.language, "translate": False, "fmt": None}   # current streaming session
    segments: queue.Queue = queue.Queue()

    def _emit(pcm) -> None:
        try:
            emit_segment(pcm, transcriber, injector, indicator, cfg.trailing_space,
                         language=st["lang"], translate=st["translate"],
                         record=record, redact=cfg.privacy, quiet=True,
                         commands=cfg.commands, cleaner=cleaner, timings=timings,
                         text_format=st["fmt"])
        except InjectionFailed as exc:
            log.error("could not type the result: %s", exc)
        except Exception:
            log.exception("segment failed")

    def on_press(language: str, translate: bool, fmt: str | None = None) -> None:
        try:
            log.info("hotkey down — listening [%s%s%s]", language,
                     "→en" if translate else "", f" {fmt}" if fmt else "")
            st["lang"], st["translate"], st["fmt"] = language, translate, fmt
            detail = (language + ("→en" if translate else "")) if language != cfg.language or translate else None
            indicator.set("listening", detail=detail)
            recorder.start()
        except Exception:
            log.exception("could not start recording")
            indicator.set("error")

    def on_release(language: str, translate: bool, fmt: str | None = None) -> None:
        if streaming:
            segments.put(recorder.stop())      # final tail; worker transcribes it
            indicator.set("ready")
            return
        try:
            handle_utterance(recorder, transcriber, injector, indicator,
                             cfg.trailing_space, language=language, translate=translate,
                             record=record, redact=cfg.privacy, commands=cfg.commands,
                             cleaner=cleaner, timings=timings, text_format=fmt)
        except InjectionFailed as exc:
            log.error("could not type the result: %s", exc)
            indicator.set("error")
        except Exception:
            log.exception("utterance failed")
            indicator.set("error")

    if streaming:
        recorder.on_endpoint = lambda: segments.put(recorder.take())

    def on_mute(muted: bool) -> None:
        indicator.set("off" if muted else "ready")

    def on_cough(active: bool) -> None:
        recorder.set_paused(active)
        if active:
            log.info("cough key — dropping audio until release")

    listener = Listener(cfg, on_press, on_release, on_mute, on_cough)
    stop = threading.Event()

    if cfg.battery_saver == "pause":
        saver = on_power_saver()
        if saver:
            listener.set_muted(True)
            log.info("power-saver active — dictation paused (battery_saver = pause)")

        def power_watch() -> None:
            prev = saver
            while not stop.wait(30):
                now = on_power_saver()
                if now != prev:
                    listener.set_muted(now)
                    log.info("power profile changed — dictation %s",
                             "paused" if now else "resumed")
                    prev = now

        threading.Thread(target=power_watch, name="power", daemon=True).start()

    def worker() -> None:
        while not stop.is_set():
            try:
                pcm = segments.get(timeout=0.3)
            except queue.Empty:
                continue
            if pcm is not None and pcm.size:
                _emit(pcm)

    if streaming:
        threading.Thread(target=worker, name="segments", daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    listener.start()
    keys = [cfg.hotkey] if isinstance(cfg.hotkey, str) else list(cfg.hotkey)
    if keys == ["KEY_F23"]:
        log.info("hotkey is KEY_F23 (the Copilot key) — set `hotkey` in config "
                 "if your keyboard doesn't have one")
    log.info("ready — %s %s to talk", "tap" if streaming else "hold", cfg.hotkey)
    try:
        stop.wait()
    finally:
        listener.stop()
        recorder.close()
        indicator.set("off")
        if timings is not None:
            timings.log_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
