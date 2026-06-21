#!/bin/bash
# Double-click this file in Finder to launch the Trailhead app.
#
# On the FIRST run it creates a private Python environment and installs the
# needed packages (this takes a few minutes). After that, launches are fast.

# Move into the folder this script lives in, regardless of where it's run from.
cd "$(dirname "$0")" || exit 1

# Guard against duplicate launches: `open` (e.g. an Automator/Dock icon) doesn't
# check whether the app is already up — each click would spawn another Terminal
# window and another process, which can step on the same database. If something
# is already listening on the app's port, just open it in the browser and exit.
APP_PORT=8501
if lsof -i :"$APP_PORT" >/dev/null 2>&1; then
    echo "Trailhead is already running — opening it in your browser."
    open "http://localhost:$APP_PORT"
    exit 0
fi

# Create the virtual environment the first time only.
if [ ! -d ".venv" ]; then
    echo "First-time setup: creating Python environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "Installing packages (this can take a few minutes)..."
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Quiet down the embedding library's noisy (harmless) startup messages.
export TRANSFORMERS_VERBOSITY=error
export TRANSFORMERS_NO_ADVISORY_WARNINGS=1
export HF_HUB_DISABLE_PROGRESS_BARS=1
export TOKENIZERS_PARALLELISM=false

# Launch the app on a fixed port so the duplicate-launch guard above can detect
# it. Streamlit opens it in your default web browser.
echo "Starting the app... (close this window to quit)"
streamlit run app.py --server.port "$APP_PORT"
