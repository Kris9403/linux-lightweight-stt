"""Entry point: wire config, injector, transcriber, recorder and hotkey together.

    python -m stt.main
"""
from __future__ import annotations

import logging
import signal
import socket
import threading

from .audio import Recorder
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


def handle_utterance(recorder, transcriber, injector, indicator, trailing_space: bool) -> None:
    pcm = recorder.stop()
    indicator.set("processing")
    text = transcriber.transcribe(pcm)
    if text:
        log.info("%.1fs audio -> %r", len(pcm) / 16000, text)
        injector.send(text + (" " if trailing_space else ""))
    else:
        log.info("%.1fs audio -> (nothing)", len(pcm) / 16000)
    indicator.set("ready")


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
        extra_hallucinations=cfg.hallucinations,
    )
    recorder = Recorder(device=cfg.audio_device)
    indicator.set("ready")

    def on_press() -> None:
        try:
            log.info("hotkey down — listening")
            indicator.set("listening")
            recorder.start()
        except Exception:
            log.exception("could not start recording")
            indicator.set("error")

    def on_release() -> None:
        try:
            handle_utterance(recorder, transcriber, injector, indicator, cfg.trailing_space)
        except Exception:
            log.exception("utterance failed")
            indicator.set("error")

    listener = Listener(cfg, on_press, on_release)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    listener.start()
    log.info("ready — hold %s to talk", cfg.hotkey)
    try:
        stop.wait()
    finally:
        listener.stop()
        recorder.close()
        indicator.set("off")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
