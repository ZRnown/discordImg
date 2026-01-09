#!/bin/bash

echo "🚀 Starting Discord Marketing System"
echo ""

# Check if virtual environment exists
if [ ! -d "backend/venv" ]; then
    echo "📦 Creating Python virtual environment..."
    cd backend
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    cd ..
fi

# Activate virtual environment
echo "🐍 Activating virtual environment..."
source backend/venv/bin/activate

# Start backend in background
echo "🔧 Starting Flask backend..."
cd backend
python app.py &
BACKEND_PID=$!

# Wait a bit for backend to start
sleep 3

# Start frontend
echo "🌐 Starting Next.js frontend..."
cd ../frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "✅ Services started!"
echo ""
echo "📋 URLs:"
echo "   • Frontend: http://localhost:3000"
echo "   • Backend:  http://localhost:5001"
echo ""
echo "🛑 To stop: kill $BACKEND_PID $FRONTEND_PID"
echo ""

# Wait for processes
wait
