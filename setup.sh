#!/bin/bash

# Setup script for Linux Lightweight PTT STT

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y libportaudio2 xdotool wtype

# Ensure user is in the 'input' group for evdev
if ! groups $USER | grep &>/dev/null "\binput\b"; then
    echo "Adding $USER to the 'input' group to allow global hotkey detection..."
    sudo usermod -aG input $USER
    echo "IMPORTANT: You MUST log out and log back in (or restart) for the group changes to take effect!"
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Installing Python dependencies..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install openvino-genai optimum[intel] nncf sounddevice numpy evdev

echo "Setup complete."
echo "To run the application, use: ./venv/bin/python ptt_stt.py"
