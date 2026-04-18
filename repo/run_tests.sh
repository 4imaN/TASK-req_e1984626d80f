#!/bin/sh
set -e

echo "=== TrailGoods Test Runner (Docker) ==="
echo ""

docker compose --profile test run --rm --build test "$@"
