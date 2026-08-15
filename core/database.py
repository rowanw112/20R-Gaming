import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Base data directory
BASE_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

def get_guild_file(guild_id: int, filename: str) -> Path:
    """Ensures the guild's specific data directory exists and returns the file path."""
    guild_dir = BASE_DATA_DIR / str(guild_id)
    guild_dir.mkdir(parents=True, exist_ok=True)
    return guild_dir / filename


# -------------------------------------------------------------------------
# HUB SETUP DASHBOARD CONFIG
# -------------------------------------------------------------------------
def load_hub_dashboard_config(guild_id: int) -> dict:
    path = get_guild_file(guild_id, "hub_dashboard.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading hub dashboard config for {guild_id}: {e}")
        return {}

def save_hub_dashboard_config(guild_id: int, data: dict) -> None:
    path = get_guild_file(guild_id, "hub_dashboard.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving hub dashboard config for {guild_id}: {e}")


# -------------------------------------------------------------------------
# THREAD SYNC DASHBOARD CONFIG
# -------------------------------------------------------------------------
def load_thread_sync_dashboard_config(guild_id: int) -> dict:
    path = get_guild_file(guild_id, "thread_sync_dashboard.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading thread sync dashboard config for {guild_id}: {e}")
        return {}

def save_thread_sync_dashboard_config(guild_id: int, data: dict) -> None:
    path = get_guild_file(guild_id, "thread_sync_dashboard.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving thread sync dashboard config for {guild_id}: {e}")


# -------------------------------------------------------------------------
# HUB DEFAULTS, MAPPINGS & DIVISIONS
# -------------------------------------------------------------------------
def load_hub_defaults(guild_id: int) -> dict:
    path = get_guild_file(guild_id, "hub_defaults.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading hub defaults for {guild_id}: {e}")
        return {}

def save_hub_defaults(guild_id: int, data: dict) -> None:
    path = get_guild_file(guild_id, "hub_defaults.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving hub defaults for {guild_id}: {e}")


def load_thread_mappings(guild_id: int) -> list[dict]:
    path = get_guild_file(guild_id, "thread_mappings.json")
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading thread mappings for {guild_id}: {e}")
        return []

def save_thread_mappings(guild_id: int, data: list[dict]) -> None:
    path = get_guild_file(guild_id, "thread_mappings.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving thread mappings for {guild_id}: {e}")


def load_division_records(guild_id: int) -> list[dict]:
    path = get_guild_file(guild_id, "division_records.json")
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading division records for {guild_id}: {e}")
        return []

def save_division_records(guild_id: int, data: list[dict]) -> None:
    path = get_guild_file(guild_id, "division_records.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving division records for {guild_id}: {e}")


# -------------------------------------------------------------------------
# LEGACY DIVISION RECORDS
# -------------------------------------------------------------------------
def load_legacy_division_records(guild_id: int) -> list[dict]:
    path = get_guild_file(guild_id, "legacy_division_records.json")
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading legacy division records for {guild_id}: {e}")
        return []

def save_legacy_division_records(guild_id: int, data: list[dict]) -> None:
    path = get_guild_file(guild_id, "legacy_division_records.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving legacy division records for {guild_id}: {e}")


# -------------------------------------------------------------------------
# CASUAL GAME RECORDS
# -------------------------------------------------------------------------
def load_casual_records(guild_id: int) -> list[dict]:
    path = get_guild_file(guild_id, "casual_records.json")
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading casual records for {guild_id}: {e}")
        return []

def save_casual_records(guild_id: int, data: list[dict]) -> None:
    path = get_guild_file(guild_id, "casual_records.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving casual records for {guild_id}: {e}")


# -------------------------------------------------------------------------
# APPLICATION SYSTEM CONFIG & THREAD MAPPINGS
# -------------------------------------------------------------------------
def load_app_config(guild_id: int) -> dict:
    path = get_guild_file(guild_id, "app_config.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading app config for {guild_id}: {e}")
        return {}

def save_app_config(guild_id: int, data: dict) -> None:
    path = get_guild_file(guild_id, "app_config.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving app config for {guild_id}: {e}")


def load_app_threads(guild_id: int) -> list[dict]:
    path = get_guild_file(guild_id, "app_threads.json")
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading app threads for {guild_id}: {e}")
        return []

def save_app_threads(guild_id: int, data: list[dict]) -> None:
    path = get_guild_file(guild_id, "app_threads.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving app threads for {guild_id}: {e}")


# -------------------------------------------------------------------------
# ROLE SYNC CONFIG
# -------------------------------------------------------------------------
def load_role_sync_config(guild_id: int) -> dict:
    path = get_guild_file(guild_id, "role_sync_config.json")
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading role sync config for {guild_id}: {e}")
        return {}

def save_role_sync_config(guild_id: int, data: dict) -> None:
    path = get_guild_file(guild_id, "role_sync_config.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving role sync config for {guild_id}: {e}")