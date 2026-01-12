#!/bin/bash

DESKTOP_IP="192.168.0.14"
LOCAL_SCRIPT="$HOME/ai-assistant/assistant.py"
LIVEKIT_DIR="$HOME/ai-assistant/oh-assistant"

# PID 파일
LOCAL_PID="/tmp/local_assistant.pid"
LIVEKIT_PID="/tmp/livekit_agent.pid"

check_desktop() {
    ping -c 1 -W 2 $DESKTOP_IP > /dev/null 2>&1
    return $?
}

start_local() {
    if [ ! -f "$LOCAL_PID" ] || ! kill -0 $(cat "$LOCAL_PID") 2>/dev/null; then
        echo "🏠 로컬 오 비서 시작..."
        cd $HOME/ai-assistant
        python3 assistant.py &
        echo $! > "$LOCAL_PID"
    fi
}

stop_local() {
    if [ -f "$LOCAL_PID" ] && kill -0 $(cat "$LOCAL_PID") 2>/dev/null; then
        echo "🏠 로컬 오 비서 중지..."
        kill $(cat "$LOCAL_PID") 2>/dev/null
        rm -f "$LOCAL_PID"
    fi
}

start_livekit() {
    if [ ! -f "$LIVEKIT_PID" ] || ! kill -0 $(cat "$LIVEKIT_PID") 2>/dev/null; then
        echo "🌐 LiveKit 에이전트 시작..."
        cd $LIVEKIT_DIR
        uv run src/agent.py dev &
        echo $! > "$LIVEKIT_PID"
    fi
}

stop_livekit() {
    if [ -f "$LIVEKIT_PID" ] && kill -0 $(cat "$LIVEKIT_PID") 2>/dev/null; then
        echo "🌐 LiveKit 에이전트 중지..."
        kill $(cat "$LIVEKIT_PID") 2>/dev/null
        rm -f "$LIVEKIT_PID"
    fi
}

echo "🤖 오 비서 자동 전환 모드 시작"
echo "데스크탑 IP: $DESKTOP_IP"
echo "Ctrl+C로 종료"
echo "================================"

LAST_STATE=""

while true; do
    if check_desktop; then
        if [ "$LAST_STATE" != "desktop" ]; then
            echo ""
            echo "💻 데스크탑 감지됨 → LiveKit 모드"
            stop_local
            start_livekit
            LAST_STATE="desktop"
        fi
    else
        if [ "$LAST_STATE" != "local" ]; then
            echo ""
            echo "📴 데스크탑 오프라인 → 로컬 모드"
            stop_livekit
            start_local
            LAST_STATE="local"
        fi
    fi
    sleep 10
done
