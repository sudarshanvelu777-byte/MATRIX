#!/usr/bin/env bash
# Builds the shared library used by the Streamlit app (app/engine_bridge.py)
# and a standalone console demo.
set -e
cd "$(dirname "$0")"

echo "Building liborderbook.so (shared library for Python/ctypes) ..."
gcc -std=gnu11 -O2 -fPIC -shared -o liborderbook.so orderbook.c -Wall -Wextra

echo "Building orderbook_cli (standalone console demo) ..."
gcc -std=gnu11 -O2 -DBUILD_CLI -o orderbook_cli orderbook.c -Wall -Wextra

echo "Done."
echo "  - liborderbook.so   -> used automatically by the Streamlit app"
echo "  - ./orderbook_cli    -> run directly for a console depth/tape/metrics demo"
