---
name: Bug report
about: Something doesn't work
labels: bug
---

**What happens**
<!-- e.g. "hold the key, speak, release — nothing is typed" -->

**What you expected**

**`python -m stt.doctor` output**
```
paste it here
```

**Service log** (last ~20 lines around a failed attempt)
```
journalctl --user -u lightweight-stt -n 20 --no-pager
```

**System**
- Distro + version:
- Desktop / compositor (GNOME, KDE, Sway, Hyprland…) and X11 or Wayland:
- Kernel (`uname -r`):
- CPU / NPU:
- Installed via `setup.sh` or manually:

**Config** (`~/.config/lightweight-stt/config.toml`, if any)
```toml
```
