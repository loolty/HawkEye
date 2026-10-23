#!/bin/bash
# Hawkeyes Optical System — Quick Start Script
# Run this from the project root or backend directory

set -e

# Determine script directory (backend/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║    Hawkeyes Optical System — Starting...                ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check if Python is available
if ! command -v python &> /dev/null; then
    echo "❌ Python is not installed or not in PATH"
    exit 1
fi

# Check if venv exists, if not create one
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null || true

# Install dependencies if needed
if [ ! -f "venv/.installed" ]; then
    echo "📥 Installing dependencies (this may take a moment)..."
    pip install -r requirements.txt --quiet
    touch venv/.installed
    echo "✅ Dependencies installed"
else
    echo "✅ Dependencies already installed"
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo ""
    echo "⚠️  .env file not found!"
    echo "   Creating from .env.example..."
    cp .env.example .env
    echo ""
    echo "📝 Please edit .env and set your MySQL credentials:"
    echo "   - DB_HOST, DB_PORT, DB_USER, DB_PASSWORD"
    echo "   - SECRET_KEY (can be any random string)"
    echo ""
    read -p "Press Enter to continue after editing .env..."
fi

# Check database connection and setup
echo ""
echo "🗄️  Checking database..."

python -c "
from app.core.config import settings, validate_settings
problems = validate_settings()
if problems:
    for p in problems:
        print(f'⚠️  Config: {p}')
print(f'   MySQL: {settings.DB_HOST}:{settings.DB_PORT}')
print(f'   DB:    {settings.DB_NAME}')
" 2>/dev/null || true

# Initialize database if needed
echo ""
read -p "Initialize/seed database? (y/n) [y]: " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ || -z $REPLY ]]; then
    echo "🔧 Setting up database..."
    python scripts/init_db.py --seed
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    Starting development server...                       ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "📍 Opening http://localhost:8000"
echo ""

# Start the server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
