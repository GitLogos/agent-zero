#!/bin/bash
set -e

# Exit immediately if a command exits with a non-zero status.
# set -e

# branch from parameter
if [ -z "$1" ]; then
    echo "Error: Branch parameter is empty. Please provide a valid branch name."
    exit 1
fi
BRANCH="$1"
REPOSITORY_URL="${A0_REPOSITORY_URL:-https://github.com/agent0ai/agent-zero}"

if [ "$BRANCH" = "local" ]; then
    # For local branch, use the files
    echo "Using local dev files in /git/agent-zero"
    # List all files recursively in the target directory
    # echo "All files in /git/agent-zero (recursive):"
    # find "/git/agent-zero" -type f | sort
else
    # For other branches, clone from GitHub
    echo "Cloning repository from $REPOSITORY_URL branch $BRANCH..."
    git clone -b "$BRANCH" "$REPOSITORY_URL" "/git/agent-zero" || {
        echo "CRITICAL ERROR: Failed to clone repository. Repository: $REPOSITORY_URL Branch: $BRANCH"
        exit 1
    }
    if [ -n "${A0_BUILD_COMMIT:-}" ]; then
        if ! [[ "$A0_BUILD_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
            echo "CRITICAL ERROR: A0_BUILD_COMMIT must be a full commit SHA." >&2
            exit 1
        fi
        # Retain a named branch for version reporting and self-update.
        git -C /git/agent-zero checkout -B "$BRANCH" "$A0_BUILD_COMMIT"
    fi
fi

. "/ins/setup_venv.sh" "$@"

# moved to base image
# # Ensure the virtual environment and pip setup
# pip install --upgrade pip ipython requests
# # Install some packages in specific variants
# pip install torch --index-url https://download.pytorch.org/whl/cpu

# Install remaining A0 python packages
additional_requirements=()
if [ -n "${A0_WHISPER_WHEEL:-}" ]; then
    if [ ! -f "$A0_WHISPER_WHEEL" ]; then
        echo "CRITICAL ERROR: Configured Whisper wheel does not exist." >&2
        exit 1
    fi
    additional_requirements+=("$A0_WHISPER_WHEEL")
fi
requirements=/git/agent-zero/requirements.txt
if [ -f /etc/a0-image-features.json ]; then
    requirements=/opt/a0-image-requirements.txt
    uv run --no-project --with packaging==25.0 --python /opt/venv-a0/bin/python \
        /ins/select_image_requirements.py /git/agent-zero/requirements.txt "$requirements"
fi
uv pip install -r "$requirements" "${additional_requirements[@]}"

# install playwright
bash /ins/install_playwright.sh "$@"

# Preload A0
python /git/agent-zero/preload.py --dockerized=true
