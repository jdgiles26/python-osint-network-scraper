#!/bin/bash

# Ensure the script is run from the project root
cd "$(dirname "$0")"

# --- Setup Virtual Environment ---
VENV_DIR="venv"

# Check for Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is not installed. Please install Python 3 to continue."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating Python virtual environment in '$VENV_DIR'..."
    python3 -m venv "$VENV_DIR" --system-site-packages
    if [ $? -ne 0 ]; then
        echo "ERROR: Failed to create virtual environment."
        exit 1
    fi
fi

# --- Activate and Install Dependencies ---
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Default Gemini key (can override by exporting GEMINI_API_KEY before running)
export GEMINI_API_KEY="${GEMINI_API_KEY:-AIzaSyA1LgNILlkH5eTReXTOQ4bBX4c-EUJ3Oto}"

echo "Upgrading pip and installing dependencies from requirements.txt..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt --upgrade
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install dependencies."
    # Optional: deactivate on failure
    deactivate
    exit 1
fi

# --- Run the Application ---
echo "Launching the Scraper Application..."
python3 src/main.py

# --- Deactivate on Exit ---
echo "Application closed. Deactivating virtual environment."
deactivate
