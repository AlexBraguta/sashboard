#!/usr/bin/env bash

# Name of the screen session
SESSION="sashboard"

# Paths (adjust if your home directory or project path differs)
VENV="$HOME/Downloads/sashboard/.venv/bin/activate"
SCRIPT="$HOME/Downloads/sashboard/main.py"

# Start a detached screen session and run the dashboard
screen -dmS "$SESSION" bash -c "
    source \"$VENV\" && \
    exec streamlit run \"$SCRIPT\"
"
