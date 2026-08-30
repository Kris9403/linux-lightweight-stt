# lightweight-stt

Push-to-talk dictation for Linux that runs Whisper on the Intel NPU instead of
the CPU or a cloud API. Hold a key, talk, let go, and the text is typed wherever
your cursor is.

I built this because the usual options didn't fit: cloud dictation is a privacy
and latency tax, and the CPU Whisper setups I tried kept a core pinned warm.
The NPU sits idle on most laptops, it's fast enough for `whisper-small`, and it
barely sips power. This just wires that up to a hotkey and `ydotool`.

Target setup is GNOME on Wayland with an Intel Core Ultra chip. Injection goes
through `ydotool` (uinput) so the text actually lands in native Wayland windows,
not only Xwayland ones.

## How it works

Audio comes off the mic through `sounddevice` into a ring buffer. An `evdev`
listener watches every keyboard for the hotkey; on release the buffered audio
goes to an OpenVINO `WhisperPipeline` pinned to the NPU, and the result is typed
out. The compiled model is cached to disk, so after the first run startup is a
second or two rather than eleven.

The default key is `KEY_F23`, which is what the Copilot key sends. It's dead
weight on Linux otherwise, it's easy to hold with a thumb, and nothing else is
bound to it. Any evdev key name works if you'd rather use something else, and
`hotkey` can be a list so a laptop key and an external-keyboard key both work.

The default `hybrid` mode gives you both styles at once: hold the key for
push-to-talk, or quick-tap it to start and tap again to stop. Set `mode` to
`hold` or `toggle` if you want just one.

The model is multilingual. Set `language` for the whole session, or give a key
its own language in `hotkey_language` — one key for English, another for Hindi,
no switching. The built-in silence filter is English-only, so junk artifacts in
other languages (Whisper loves emitting `"Sous-titres réalisés…"` on French
silence) need adding to `hallucinations` yourself.

A few smaller things it does: text longer than ~50 characters (or mostly
non-ASCII) is pasted via the clipboard instead of typed key-by-key, and the old
clipboard contents are put back afterwards. Recordings shorter than 300 ms are
ignored, and Whisper's habit of emitting `"you"` or `"Thank you."` on silence is
filtered out.

## Requirements

- An Intel NPU with the `intel-npu-level-zero` driver.
- Membership in the `render` group (or OpenVINO quietly falls back to the CPU)
  and the `input` group (for reading the keyboard).
- On Wayland: `ydotool` with `ydotoold` running, plus a udev rule that lets your
  session open `/dev/uinput`. `setup.sh` sets all of that up.
- The converted model in `whisper-small-ov/` — see below.

## Setup

```
./setup.sh
```

That installs the system packages, adds you to the groups, drops in the udev
rule, builds the venv, and enables a `systemd --user` service. Log out and back
in once so the group changes take. After that:

```
systemctl --user status lightweight-stt
journalctl --user -u lightweight-stt -f
```

or just run `./venv/bin/python -m stt.main` in a terminal.

If something doesn't work, run the checker first — it tests the NPU, the
groups, `ydotoold`, `/dev/uinput`, the model, and the mic, and prints the exact
command to fix whatever failed:

```
./venv/bin/python -m stt.doctor
```

## Other compositors

Built and tested on GNOME Wayland. The moving parts aren't GNOME-specific:
`ydotool` (uinput) and `wl-clipboard` work the same on KDE Plasma, Sway and
Hyprland, and `notify-send` works anywhere a notification daemon runs. The only
GNOME-ish bit is the `canberra-gtk-play` beep, which just no-ops elsewhere
(`indicator = "notify"` or `"off"` if you don't want it trying). On X11 it falls
back to `xdotool`. Untested outside GNOME — reports welcome.

## The model

`whisper-small-ov/` is an INT8 OpenVINO export of `openai/whisper-small`, about
250 MB, and it's not in git. `./convert.sh` regenerates it with `optimum-cli` in
a throwaway venv.

## Config

Optional, at `~/.config/lightweight-stt/config.toml`. Anything you leave out
keeps its default.

| key | default | meaning |
|---|---|---|
| `mode` | `hybrid` | `hybrid` (hold to talk, or quick-tap to latch until the next tap), `hold`, `toggle`, or `streaming` (acts like toggle for now) |
| `tap_ms` | `350` | in `hybrid`, a press shorter than this counts as a toggle tap rather than a hold |
| `hotkey` | `KEY_F23` | evdev key name to hold, or a list — `["KEY_F23", "KEY_SCROLLLOCK"]` — so a laptop key and an external one both work |
| `hotkey_language` | `{}` | table mapping a key to a language, e.g. `[hotkey_language]` then `KEY_SCROLLLOCK = "hi"` — that key dictates in Hindi, everything else uses `language`. Keys here are listened for even if not in `hotkey` |
| `hotkey_translate` | `[]` | keys whose output is translated to English — e.g. `hotkey_translate = ["KEY_SCROLLLOCK"]` with `KEY_SCROLLLOCK = "hi"` means "speak Hindi, type English" |
| `mute_hotkey` | `""` | a key that pauses/resumes the whole listener (indicator goes to "off"). Pick one you don't dictate with, e.g. `"KEY_CAPSLOCK"` |
| `device` | `NPU` | OpenVINO device — `NPU`, `GPU`, or `CPU` |
| `language` | `en` | Whisper language; the default for any key without a `hotkey_language` entry |
| `keyboard` | `auto` | watch every keyboard, or pin one `/dev/input/eventN` |
| `audio_device` | unset | mic to record from — a `sounddevice` index or name substring; unset uses the system default |
| `inject_method` | `auto` | `auto`, `ydotool`, `paste`, or `xdotool` |
| `paste_threshold` | `50` | characters above which the clipboard path is used |
| `paste_settle_ms` | `150` | pause after Ctrl+V before restoring the old clipboard; raise it if a slow app pastes stale text |
| `hallucinations` | `[]` | extra phrases to drop on top of the built-in silence list (e.g. a noise your fan triggers) |
| `vocabulary` | `[]` | names / jargon to bias the model toward, e.g. `["Kubernetes", "Anthropic"]`. **GPU/CPU only** — the NPU's fixed decoder context can't take the extra tokens, so it's ignored with a warning there |
| `num_beams` | `1` | beam-search width; `>1` improves accuracy on hard audio at a speed cost. **GPU/CPU only** — the NPU can't batch beams, so it's forced back to greedy with a warning |
| `indicator` | `both` | `notify`, `beep`, `both`, or `off` |
| `trailing_space` | `true` | add a space after each insertion |
| `min_speech_ms` | `300` | drop anything shorter |
| `history` | `true` | append each insertion (timestamp, language, text) to `$XDG_STATE_HOME/lightweight-stt/history.log` |

## Transcribing a file

```
./venv/bin/python -m stt.transcribe recording.mp4
./venv/bin/python -m stt.transcribe interview.m4a --language hi --translate
```

Anything ffmpeg can read (audio or video). `--device` overrides the configured one.

## HTTP server

`stt_server.py` exposes the same transcriber over HTTP for other tools to call —
`POST /transcribe` (raw 16 kHz float32 PCM, or a multipart `audio` file in any
format ffmpeg reads) and `GET /health`. Run it with
`./venv/bin/uvicorn stt_server:app`.

## Development

```
./venv/bin/pip install -r requirements-dev.txt
./venv/bin/python -m pytest tests/
```

The transcriber tests load the real model on the NPU, so they take a couple of
seconds. `docs/design.md` has the reasoning behind the structure.
