#!/bin/bash
# Test script for Technical Machine AI bot
# Verifies TM is built, connects to Showdown, and can play a battle

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
TM_DIR="$PROJECT_DIR/technical-machine"
SHOWDOWN_DIR="$PROJECT_DIR/pokemon-showdown"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=============================================="
echo "Technical Machine Test"
echo "=============================================="
echo ""

# Step 1: Check if TM is built
echo -e "${YELLOW}[1/5] Checking Technical Machine build...${NC}"
TM_EXECUTABLE="$TM_DIR/build/ai"

if [ ! -f "$TM_EXECUTABLE" ]; then
    echo -e "${RED}ERROR: Technical Machine not built.${NC}"
    echo ""
    echo "Run the setup script first:"
    echo "  bash scripts/setup_technical_machine.sh"
    echo ""
    exit 1
fi
echo -e "${GREEN}  ✓ Technical Machine executable found${NC}"

# Step 2: Check if Showdown server is running
echo ""
echo -e "${YELLOW}[2/5] Checking Pokemon Showdown server...${NC}"

check_showdown() {
    curl -s -o /dev/null -w "%{http_code}" http://localhost:8000 2>/dev/null || echo "000"
}

SHOWDOWN_STATUS=$(check_showdown)

if [ "$SHOWDOWN_STATUS" != "200" ] && [ "$SHOWDOWN_STATUS" != "304" ]; then
    echo -e "${YELLOW}  ! Showdown server not running${NC}"

    if [ ! -d "$SHOWDOWN_DIR" ]; then
        echo -e "${RED}ERROR: Pokemon Showdown not installed.${NC}"
        echo ""
        echo "Run the setup script first:"
        echo "  bash scripts/setup_showdown.sh"
        echo ""
        exit 1
    fi

    echo "  Starting Showdown server in background..."
    cd "$SHOWDOWN_DIR"
    node pokemon-showdown start --no-security > /tmp/showdown.log 2>&1 &
    SHOWDOWN_PID=$!
    echo "  Showdown PID: $SHOWDOWN_PID"

    # Wait for server to start
    echo "  Waiting for server to be ready..."
    for i in {1..30}; do
        sleep 1
        SHOWDOWN_STATUS=$(check_showdown)
        if [ "$SHOWDOWN_STATUS" = "200" ] || [ "$SHOWDOWN_STATUS" = "304" ]; then
            break
        fi
        echo -n "."
    done
    echo ""

    if [ "$SHOWDOWN_STATUS" != "200" ] && [ "$SHOWDOWN_STATUS" != "304" ]; then
        echo -e "${RED}ERROR: Failed to start Showdown server.${NC}"
        echo "Check /tmp/showdown.log for details."
        exit 1
    fi

    STARTED_SHOWDOWN=true
else
    STARTED_SHOWDOWN=false
fi

echo -e "${GREEN}  ✓ Showdown server is running${NC}"

# Step 3: Configure Technical Machine
echo ""
echo -e "${YELLOW}[3/5] Configuring Technical Machine...${NC}"

TM_SETTINGS_DIR="$TM_DIR/build/settings"
TM_SETTINGS="$TM_SETTINGS_DIR/settings.json"
TM_TEAM_DIR="$PROJECT_DIR/Raw-Teams"

mkdir -p "$TM_SETTINGS_DIR"

# Create settings.json for local testing
cat > "$TM_SETTINGS" << EOF
{
    "server": "ws://localhost:8000/showdown/websocket",
    "username": "TechnicalMachine",
    "password": "",
    "team_directory": "$TM_TEAM_DIR",
    "format": "gen4ou",
    "accept_challenges": true,
    "auto_search": false
}
EOF

echo -e "${GREEN}  ✓ Settings configured${NC}"
echo "    Server: ws://localhost:8000/showdown/websocket"
echo "    Username: TechnicalMachine"

# Step 4: Start Technical Machine
echo ""
echo -e "${YELLOW}[4/5] Starting Technical Machine...${NC}"

cd "$TM_DIR/build"
./ai > /tmp/technical_machine.log 2>&1 &
TM_PID=$!
echo "  Technical Machine PID: $TM_PID"

# Give TM time to connect
sleep 3

# Check if TM is still running
if ! kill -0 $TM_PID 2>/dev/null; then
    echo -e "${RED}ERROR: Technical Machine crashed on startup.${NC}"
    echo "Check /tmp/technical_machine.log for details:"
    echo ""
    tail -20 /tmp/technical_machine.log
    exit 1
fi

echo -e "${GREEN}  ✓ Technical Machine started${NC}"

# Step 5: Run a test battle
echo ""
echo -e "${YELLOW}[5/5] Running test battle vs Random Bot...${NC}"

cd "$PROJECT_DIR"

# Run the Python test script
python3 - << 'PYTHON_SCRIPT'
import asyncio
import sys
sys.path.insert(0, '.')

from poke_env.player import Player, RandomPlayer
from poke_env import ServerConfiguration

SERVER_CONFIG = ServerConfiguration(
    websocket_url="ws://localhost:8000/showdown/websocket",
    authentication_url="https://play.pokemonshowdown.com/action.php?"
)

async def test_battle():
    """Challenge Technical Machine to a battle."""

    # Create a random player to challenge TM
    challenger = RandomPlayer(
        battle_format="gen4ou",
        server_configuration=SERVER_CONFIG,
        max_concurrent_battles=1,
    )

    print("  Challenging TechnicalMachine to a battle...")
    print("  (Timeout: 60 seconds)")

    try:
        # Send challenge to Technical Machine
        await asyncio.wait_for(
            challenger.send_challenges("TechnicalMachine", n_challenges=1),
            timeout=60
        )

        # Check result
        if challenger.n_finished_battles > 0:
            if challenger.n_won_battles > 0:
                print("  Result: Random Bot won!")
            else:
                print("  Result: Technical Machine won!")
            return True
        else:
            print("  ERROR: Battle did not complete")
            return False

    except asyncio.TimeoutError:
        print("  ERROR: Battle timed out (TM may not be accepting challenges)")
        return False
    except Exception as e:
        print(f"  ERROR: {e}")
        return False

success = asyncio.run(test_battle())
sys.exit(0 if success else 1)
PYTHON_SCRIPT

TEST_RESULT=$?

# Cleanup
echo ""
echo "Cleaning up..."

if [ -n "$TM_PID" ]; then
    kill $TM_PID 2>/dev/null || true
    echo "  Stopped Technical Machine (PID: $TM_PID)"
fi

if [ "$STARTED_SHOWDOWN" = true ] && [ -n "$SHOWDOWN_PID" ]; then
    kill $SHOWDOWN_PID 2>/dev/null || true
    echo "  Stopped Showdown server (PID: $SHOWDOWN_PID)"
fi

echo ""
echo "=============================================="
if [ $TEST_RESULT -eq 0 ]; then
    echo -e "${GREEN}Technical Machine test PASSED!${NC}"
    echo ""
    echo "TM is working correctly. You can now:"
    echo "  1. Start TM manually: cd technical-machine/build && ./ai"
    echo "  2. Run tournaments with TM as an external participant"
else
    echo -e "${RED}Technical Machine test FAILED${NC}"
    echo ""
    echo "Check logs for details:"
    echo "  - TM log: /tmp/technical_machine.log"
    echo "  - Showdown log: /tmp/showdown.log"
fi
echo "=============================================="

exit $TEST_RESULT
