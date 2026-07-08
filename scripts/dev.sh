#!/bin/bash
set -e

# Load environment variables from .env file
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

# Function to cleanup background processes
cleanup() {
    echo ""
    echo "Stopping servers..."
    if [ ! -z "$DJANGO_PID" ]; then
        echo "Stopping Django server..."
        kill $DJANGO_PID 2>/dev/null || true
        wait $DJANGO_PID 2>/dev/null || true
    fi
    if [ ! -z "$NPM_PID" ]; then
        echo "Stopping npm dev server..."
        kill $NPM_PID 2>/dev/null || true
        wait $NPM_PID 2>/dev/null || true
    fi
    echo "Done."
    exit 0
}

# Set up signal handlers for graceful shutdown
trap cleanup INT TERM

# Default ports
DJANGO_PORT=${DJANGO_PORT:-8000}
DJANGO_VITE_PORT=${DJANGO_VITE_PORT:-5173}

echo "🚀 Starting development environment..."
echo ""

echo "Starting Django development server on port $DJANGO_PORT..."
uv run manage.py runserver $DJANGO_PORT &
DJANGO_PID=$!

echo "Starting npm dev server on port $DJANGO_VITE_PORT..."
npm run dev &
NPM_PID=$!

# Wait for any process to exit
wait
