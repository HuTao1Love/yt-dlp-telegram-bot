#!/bin/bash

set -a
if [ -f ./.env ]; then
	. ./.env
fi
set +a

mkdir -p data

exec python3 /app/bot.py
