#!/bin/bash
# Double-click this file in Finder to launch the Link Library app.
#
# On the FIRST run it creates a private Python environment and installs the
# needed packages (this takes a few minutes). After that, launches are fast.

# Move into the folder this script lives in, regardless of where it's run from.
cd "$(dirname "$0")" || exit 1

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

# Launch the app. Streamlit opens it in your default web browser.
echo "Starting the app... (close this window to quit)"
streamlit run app.py
