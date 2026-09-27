#!/bin/bash
# ============================================
# IBVAP — One-Click Demo Launcher
# ============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "════════════════════════════════════════════════"
echo "  IBVAP — Intelligent Border Video Analytics"
echo "  Demo Launcher"
echo "════════════════════════════════════════════════"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is required but not installed."
    exit 1
fi

# Create .env if missing
if [ ! -f "$PROJECT_ROOT/.env" ]; then
    echo "📋 Creating .env from template..."
    cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
fi

# Generate sample video
echo ""
echo "🎬 Setting up sample data..."
cd "$PROJECT_ROOT"
python3 scripts/download_models.py

# Start Core Backend
echo ""
echo "🚀 Starting Core Backend (FastAPI)..."
cd "$PROJECT_ROOT"
python3 -m core.main &
CORE_PID=$!
echo "   Core PID: $CORE_PID"
sleep 3

# Start Dashboard
echo ""
echo "🌐 Starting Web Dashboard (Next.js)..."
cd "$PROJECT_ROOT/web/dashboard"
npm run dev &
WEB_PID=$!
echo "   Dashboard PID: $WEB_PID"
sleep 3

echo ""
echo "════════════════════════════════════════════════"
echo "  IBVAP Demo Running!"
echo "════════════════════════════════════════════════"
echo ""
echo "  📡 Core API:      http://localhost:8000"
echo "  📚 API Docs:      http://localhost:8000/docs"
echo "  🖥️  Dashboard:     http://localhost:3000"
echo ""
echo "  To run Edge Pipeline (separate terminal):"
echo "    cd $PROJECT_ROOT && python3 -m edge.main"
echo ""
echo "  Press Ctrl+C to stop all services."
echo "════════════════════════════════════════════════"

# Wait for interrupt
trap "echo ''; echo 'Shutting down...'; kill $CORE_PID $WEB_PID 2>/dev/null; exit 0" INT TERM
wait
