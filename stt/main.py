"""Entry point: wire config, injector, transcriber, recorder and hotkey together.

    python -m stt.main
"""
from __future__ import annotations

import logging
import os
import queue
import signal
import socket
import threading
from datetime import datetime
from pathlib import Path

from .audio import EndpointDetector, Recorder
from .config import load
from .hotkey import Listener
from .indicator import Indicator
from .inject import NoInjectorError, probe
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


def emit_segment(pcm, transcriber, injector, indicator, trailing_space: bool,
                 language: str | None = None, translate: bool = False,
                 record: Path | None = None, redact: bool = False,
                 quiet: bool = False) -> None:
    """Transcribe one audio segment and type it. Shared by push-to-talk and the
    continuous-mode worker. `quiet` skips the indicator so the chime can't feed
    back into the mic between segments."""
    text = transcriber.transcribe(pcm, language=language, translate=translate)
    tag = f" [{language}{'→en' if translate else ''}]" if language else ""
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
                     record: Path | None = None, redact: bool = False) -> None:
    pcm = recorder.stop()
    indicator.set("processing")
    emit_segment(pcm, transcriber, injector, indicator, trailing_space,
                 language=language, translate=translate, record=record, redact=redact)


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
    st = {"lang": cfg.language, "translate": False}   # current streaming session
    segments: queue.Queue = queue.Queue()

    def _emit(pcm) -> None:
        try:
            emit_segment(pcm, transcriber, injector, indicator, cfg.trailing_space,
                         language=st["lang"], translate=st["translate"],
                         record=record, redact=cfg.privacy, quiet=True)
        except Exception:
            log.exception("segment failed")

    def on_press(language: str, translate: bool) -> None:
        try:
            log.info("hotkey down — listening [%s%s]", language, "→en" if translate else "")
            st["lang"], st["translate"] = language, translate
            detail = (language + ("→en" if translate else "")) if language != cfg.language or translate else None
            indicator.set("listening", detail=detail)
            recorder.start()
        except Exception:
            log.exception("could not start recording")
            indicator.set("error")

    def on_release(language: str, translate: bool) -> None:
        if streaming:
            segments.put(recorder.stop())      # final tail; worker transcribes it
            indicator.set("ready")
            return
        try:
            handle_utterance(recorder, transcriber, injector, indicator,
                             cfg.trailing_space, language=language, translate=translate,
                             record=record, redact=cfg.privacy)
        except Exception:
            log.exception("utterance failed")
            indicator.set("error")

    if streaming:
        recorder.on_endpoint = lambda: segments.put(recorder.take())

    def on_mute(muted: bool) -> None:
        indicator.set("off" if muted else "ready")

    listener = Listener(cfg, on_press, on_release, on_mute)
    stop = threading.Event()

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
    log.info("ready — %s %s to talk", "tap" if streaming else "hold", cfg.hotkey)
    try:
        stop.wait()
    finally:
        listener.stop()
        recorder.close()
        indicator.set("off")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
