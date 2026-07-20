#!/bin/bash
# Quick setup for Lissa mobile development

set -e

echo "🍋 Setting up Lissa mobile development..."

# Check if Node.js is installed
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Please install Node.js first."
    exit 1
fi

# Check if npm is installed
if ! command -v npm &> /dev/null; then
    echo "❌ npm not found. Please install npm first."
    exit 1
fi

echo "✓ Node.js and npm found"

# Install dependencies if not already installed
if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
else
    echo "✓ Dependencies already installed"
fi

# Check if Android SDK is set up
if [ -z "$ANDROID_SDK_ROOT" ]; then
    echo ""
    echo "⚠️  ANDROID_SDK_ROOT not set. To build Android:"
    echo "   1. Install Android Studio from https://android.google.com/studio"
    echo "   2. Set ANDROID_SDK_ROOT: export ANDROID_SDK_ROOT=\$HOME/Library/Android/sdk"
    echo ""
fi

# Summary
echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo ""
echo "📱 For Android development:"
echo "   npm run cap:open:android"
echo ""
echo "🍎 For iOS development (macOS only):"
echo "   npm run cap:open:ios"
echo ""
echo "📚 Full instructions: see MOBILE.md"
echo ""
