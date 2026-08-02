import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Discord Bot Token
TOKEN = os.getenv("DISCORD_TOKEN")

# Convert comma-separated GUILD_IDS into a list of integers
raw_guilds = os.getenv("GUILD_IDS", "")
GUILD_IDS = [int(gid.strip()) for gid in raw_guilds.split(",") if gid.strip().isdigit()]

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
THREAD_MAPPINGS_FILE = DATA_DIR / "thread_mappings.json"