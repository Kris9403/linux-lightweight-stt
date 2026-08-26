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
bound to it. Any evdev key name works if you'd rather use something else.

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

## The model

`whisper-small-ov/` is an INT8 OpenVINO export of `openai/whisper-small`, about
250 MB, and it's not in git. `./convert.sh` regenerates it with `optimum-cli` in
a throwaway venv.

## Config

Optional, at `~/.config/lightweight-stt/config.toml`. Anything you leave out
keeps its default.

| key | default | meaning |
|---|---|---|
| `mode` | `hold` | `hold`, `toggle`, or `streaming` (streaming currently acts like toggle) |
| `hotkey` | `KEY_F23` | evdev key name to hold, or a list — `["KEY_F23", "KEY_SCROLLLOCK"]` — so a laptop key and an external one both work |
| `device` | `NPU` | OpenVINO device — `NPU`, `GPU`, or `CPU` |
| `language` | `en` | Whisper language |
| `keyboard` | `auto` | watch every keyboard, or pin one `/dev/input/eventN` |
| `audio_device` | unset | mic to record from — a `sounddevice` index or name substring; unset uses the system default |
| `inject_method` | `auto` | `auto`, `ydotool`, `paste`, or `xdotool` |
| `paste_threshold` | `50` | characters above which the clipboard path is used |
| `indicator` | `both` | `notify`, `beep`, `both`, or `off` |
| `trailing_space` | `true` | add a space after each insertion |
| `min_speech_ms` | `300` | drop anything shorter |

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
