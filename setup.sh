#!/bin/bash
# ============================================
# IBVAP — Environment Setup Script
# ============================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "════════════════════════════════════════════════"
echo "  IBVAP — Environment Setup"
echo "════════════════════════════════════════════════"
echo ""

# Step 1: Create virtual environment
echo "📦 Step 1: Creating Python virtual environment..."
if [ -d "venv" ]; then
    echo "   Virtual environment already exists. Recreating..."
    rm -rf venv
fi

python3 -m venv venv
echo "   ✅ Virtual environment created at ./venv/"

# Step 2: Activate venv and install all requirements
echo ""
echo "📦 Step 2: Installing Python dependencies..."
source venv/bin/activate
echo "   Using Python: $(which python3)"
echo "   Python version: $(python3 --version)"

pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt 2>&1 | while read line; do
    if echo "$line" | grep -q "Successfully installed"; then
        echo "   ✅ $line"
    elif echo "$line" | grep -q "Requirement already"; then
        :
    elif echo "$line" | grep -q "ERROR"; then
        echo "   ❌ $line"
    fi
done

# Step 3: Verify critical imports
echo ""
echo "🔍 Step 3: Verifying installations..."
python3 -c "
imports = {
    'fastapi': 'FastAPI',
    'uvicorn': 'Uvicorn',
    'cv2': 'OpenCV',
    'numpy': 'NumPy',
    'sqlalchemy': 'SQLAlchemy',
    'aiosqlite': 'AioSQLite',
    'pydantic': 'Pydantic',
    'jose': 'Python-JOSE',
    'PIL': 'Pillow',
    'httpx': 'HTTPX',
    'websockets': 'WebSockets',
    'greenlet': 'Greenlet',
}
all_ok = True
for mod, name in imports.items():
    try:
        __import__(mod)
        print(f'   ✅ {name}')
    except ImportError:
        print(f'   ❌ {name} — FAILED')
        all_ok = False

if all_ok:
    print()
    print('   All libraries installed successfully!')
else:
    print()
    print('   Some libraries failed to install. Check errors above.')
    exit(1)
"

# Step 4: Create .env if not exists
echo ""
echo "📋 Step 4: Setting up environment..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "   ✅ Created .env from .env.example"
else
    echo "   ✅ .env already exists"
fi

# Step 5: Setup sample data
echo ""
echo "🎬 Step 5: Setting up sample data..."
python3 scripts/download_models.py 2>&1 | grep -E "(✓|✗|ℹ|🎬|═|Setup)" | head -10

echo ""
echo "════════════════════════════════════════════════"
echo "  ✅ IBVAP Setup Complete!"
echo "════════════════════════════════════════════════"
echo ""
echo "  To run the project, use SEPARATE terminals:"
echo ""
echo "  Terminal 1 (Core API):"
echo "    cd $(pwd)"
echo "    source venv/bin/activate"
echo "    python3 -m core.main"
echo ""
echo "  Terminal 2 (Dashboard):"
echo "    cd $(pwd)/web/dashboard"
echo "    npm run dev"
echo ""
echo "  Terminal 3 (Edge Pipeline):"
echo "    cd $(pwd)"
echo "    source venv/bin/activate"
echo "    python3 -m edge.main --source sample"
echo ""
echo "════════════════════════════════════════════════"
