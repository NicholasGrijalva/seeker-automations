#!/bin/bash
# CognosMap Automation Setup Script

echo "🚀 Setting up CognosMap Automation..."

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env from example if it doesn't exist
if [ ! -f .env ]; then
    cp .env.example .env
    echo "📝 Created .env file - please fill in your API keys"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run: source venv/bin/activate"
echo "  3. Test: python scripts/cli.py check"
echo ""
