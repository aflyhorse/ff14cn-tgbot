#!/bin/bash

# FF14CN Telegram Bot Management Script
# Usage: ./service.sh {start|stop|restart|status}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/.venv"
PID_FILE="$SCRIPT_DIR/bot.pid"
LOG_FILE="$SCRIPT_DIR/logs/bot.log"

# Function to start the bot
start() {
    if [ -f "$PID_FILE" ]; then
        echo "Bot is already running (PID: $(cat $PID_FILE))"
        exit 1
    fi

    echo "Starting bot..."
    source "$VENV_PATH/bin/activate"
    nohup python "$SCRIPT_DIR/main.py" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "Bot started with PID: $(cat $PID_FILE)"
}

# Function to stop the bot
stop() {
    if [ ! -f "$PID_FILE" ]; then
        echo "Bot is not running"
        exit 1
    fi

    PID=$(cat "$PID_FILE")
    echo "Stopping bot (PID: $PID)..."
    kill "$PID"
    rm "$PID_FILE"
    echo "Bot stopped"
}

# Function to restart the bot
restart() {
    stop
    sleep 2
    start
}

# Main case statement
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        if [ -f "$PID_FILE" ]; then
            PID=$(cat "$PID_FILE")
            if ps -p "$PID" > /dev/null; then
                echo "Bot is running (PID: $PID)"
            else
                echo "Bot is not running (stale PID file)"
                rm "$PID_FILE"
            fi
        else
            echo "Bot is not running"
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
esac