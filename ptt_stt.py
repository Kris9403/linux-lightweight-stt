import os
import sys
import numpy as np
import sounddevice as sd
import queue
import subprocess
import threading
import evdev
from evdev import ecodes
import openvino_genai as ov_genai
import time
import tkinter as tk

# --- Configuration ---
MODEL_DIR = "whisper-small-ov"
DEVICE = "NPU"
HOTKEY_CODE = ecodes.KEY_F12
MODIFIER_CODE = ecodes.KEY_LEFTCTRL # For mode switching
SAMPLE_RATE = 16000
CHANNELS = 1

# Modes
MODE_OFF = 0
MODE_TOGGLE = 1
MODE_STREAMING = 2
MODE_NAMES = ["OFF", "TOGGLE", "STREAMING"]

# --- Global State ---
audio_queue = queue.Queue()
recording = False
ui_ready = threading.Event()
current_mode = MODE_TOGGLE

class IndicatorUI:
    def __init__(self):
        self.root = None
        self.label = None
        self.mode_label = None

    def run(self):
        self.root = tk.Tk()
        self.root.title("PTT Status")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        
        screen_width = self.root.winfo_screenwidth()
        self.root.geometry(f"150x50+{int(screen_width/2)-75}+0")
        
        self.label = tk.Label(self.root, text="READY", bg="red", fg="white", font=("Arial", 10, "bold"))
        self.label.pack(expand=True, fill="both")
        
        self.mode_label = tk.Label(self.root, text="MODE: TOGGLE", bg="black", fg="gray", font=("Arial", 8))
        self.mode_label.pack(fill="x")
        
        ui_ready.set()
        self.root.mainloop()
        
    def set_state(self, state):
        if state == "recording":
            self.label.config(text="LISTENING", bg="green", fg="white")
        elif state == "processing":
            self.label.config(text="PROCESSING", bg="orange", fg="black")
        elif state == "streaming":
            self.label.config(text="STREAMING", bg="cyan", fg="black")
        elif state == "ready":
            self.label.config(text="READY", bg="red", fg="white")
        elif state == "off":
            self.label.config(text="OFF", bg="#333", fg="white")
            
    def update_mode(self, mode_name):
        self.mode_label.config(text=f"MODE: {mode_name}")

indicator = None

def update_ui(state=None, mode_name=None):
    if indicator and indicator.root:
        if mode_name:
            indicator.root.after(0, lambda: indicator.update_mode(mode_name))
        if state:
            indicator.root.after(0, lambda: indicator.set_state(state))

def get_keyboard_device():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    for device in devices:
        capabilities = device.capabilities()
        if ecodes.EV_KEY in capabilities:
            if ecodes.KEY_A in capabilities[ecodes.EV_KEY]:
                return device
    return None

def audio_callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    if recording or current_mode == MODE_STREAMING:
        audio_queue.put(indata.copy())

def type_text(text):
    text = text.strip()
    if not text: return
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    cmd = ["wtype"] if session_type == "wayland" else ["xdotool", "type", "--clearmodifiers"]
    try:
        subprocess.run(cmd + [text], check=True)
    except Exception as e:
        print(f"Error typing: {e}")

def play_feedback_tone(freq=440, duration=0.1):
    t = np.linspace(0, duration, int(SAMPLE_RATE * duration), False)
    tone = np.sin(freq * t * 2 * np.pi)
    sd.play(tone, SAMPLE_RATE)
    sd.wait()

def streaming_worker(pipe):
    while True:
        if current_mode == MODE_STREAMING:
            chunks = []
            while current_mode == MODE_STREAMING:
                try:
                    chunk = audio_queue.get(timeout=0.1)
                    chunks.append(chunk)
                    # If silence or max duration (5s) reached
                    if len(chunks) > 20: # ~1s minimum
                        if np.max(np.abs(chunk)) < 0.01 or len(chunks) > 100:
                            break
                except queue.Empty:
                    if chunks: break
                    continue
            
            if chunks and current_mode == MODE_STREAMING:
                audio_data = np.concatenate(chunks).flatten()
                if len(audio_data) > 8000:
                    update_ui("processing")
                    try:
                        result = pipe.generate(audio_data.tolist())
                        transcription = result.texts[0] if result.texts else ""
                        if transcription.strip():
                            type_text(transcription + " ")
                    except: pass
                update_ui("streaming")
        else:
            time.sleep(0.2)

def main():
    global recording, indicator, current_mode
    
    indicator = IndicatorUI()
    threading.Thread(target=indicator.run, daemon=True).start()
    ui_ready.wait()

    print("Loading Whisper model onto NPU...")
    pipe = ov_genai.WhisperPipeline(MODEL_DIR, DEVICE)
    print("Ready.")
    
    threading.Thread(target=streaming_worker, args=(pipe,), daemon=True).start()
    update_ui("ready", MODE_NAMES[current_mode])

    kb_device = get_keyboard_device()
    if not kb_device: return

    stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, callback=audio_callback)
    stream.start()

    modifier_pressed = False
    try:
        for event in kb_device.read_loop():
            if event.type == ecodes.EV_KEY:
                data = evdev.categorize(event)
                if data.scancode == MODIFIER_CODE:
                    modifier_pressed = (data.keystate != evdev.KeyEvent.key_up)
                    continue

                if data.scancode == HOTKEY_CODE and data.keystate == 1:
                    if modifier_pressed:
                        current_mode = (current_mode + 1) % 3
                        recording = False
                        while not audio_queue.empty(): audio_queue.get()
                        
                        mode_name = MODE_NAMES[current_mode]
                        print(f"Mode: {mode_name}")
                        
                        if current_mode == MODE_OFF: update_ui("off", mode_name)
                        elif current_mode == MODE_STREAMING: update_ui("streaming", mode_name)
                        else: update_ui("ready", mode_name)
                        
                        play_feedback_tone(1000, 0.05)
                    elif current_mode == MODE_TOGGLE:
                        if not recording:
                            play_feedback_tone(660, 0.05)
                            recording = True
                            update_ui("recording")
                            while not audio_queue.empty(): audio_queue.get()
                        else:
                            recording = False
                            update_ui("processing")
                            play_feedback_tone(440, 0.05)
                            chunks = []
                            while not audio_queue.empty(): chunks.append(audio_queue.get())
                            if chunks:
                                audio_data = np.concatenate(chunks).flatten()
                                try:
                                    result = pipe.generate(audio_data.tolist())
                                    transcription = result.texts[0] if result.texts else ""
                                    if transcription: type_text(transcription)
                                except: pass
                            update_ui("ready")
    except KeyboardInterrupt: pass
    finally:
        stream.stop()
        stream.close()

if __name__ == "__main__":
    main()
