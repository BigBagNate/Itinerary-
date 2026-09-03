#!/bin/bash
# Double-click this file to start the workbench.
cd "$(dirname "$0")" || exit 1
echo ""
echo "  Starting your Itinerary Workbench..."
echo "  It will open in your browser in a second."
echo ""
echo "  To stop it: close this window, or press Control + C."
echo ""
( sleep 2; open "http://127.0.0.1:8000" ) &
./.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000
