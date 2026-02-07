#!/bin/bash
# Setup Pokemon Showdown server for local development

set -e

echo "Setting up Pokemon Showdown server..."

# Clone Pokemon Showdown if not already present
if [ ! -d "pokemon-showdown" ]; then
    echo "Cloning Pokemon Showdown..."
    git clone https://github.com/smogon/pokemon-showdown.git
fi

cd pokemon-showdown

# Install dependencies
echo "Installing dependencies..."
npm install

# Copy config (required)
if [ ! -f "config/config.js" ]; then
    echo "Creating config file..."
    cp config/config-example.js config/config.js
fi

echo ""
echo "Setup complete!"
echo ""
echo "To start the server, run:"
echo "  cd pokemon-showdown && node pokemon-showdown start --no-security"
echo ""
echo "The server will be available at http://localhost:8088"
echo "You can watch battles in your browser at that URL."
