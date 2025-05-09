#!/usr/bin/env bash

# Name of the screen session
SESSION="sashboard"

# Paths (adjust if your home directory or project path differs)
VENV="$HOME/Documents/PycharmProjects/sashboard/.venv/bin/activate"
SCRIPT="$HOME/Documents/PycharmProjects/sashboard/main.py"

# Start a detached screen session and run the dashboard
screen -dmS "$SESSION" bash -c "
    source \"$VENV\" && \
    exec streamlit run \"$SCRIPT\"
"
