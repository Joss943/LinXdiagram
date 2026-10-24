#!/bin/sh
# Lance LinXdiagram depuis les sources, sans installation.
cd "$(dirname "$0")" && exec python3 -P -m linxdiagram "$@"
