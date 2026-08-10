import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

HUB_DASHBOARD_FILE = DATA_DIR / "hub_dashboard.json"
THREAD_SYNC_DASHBOARD_FILE = DATA_DIR / "thread_sync_dashboard.json"
HUB_DEFAULTS_FILE = DATA_DIR / "hub_defaults.json"
THREAD_MAPPINGS_FILE = DATA_DIR / "thread_mappings.json"
DIVISION_RECORDS_FILE = DATA_DIR / "division_records.json"
APP_CONFIG_FILE = DATA_DIR / "app_config.json"
APP_THREADS_FILE = DATA_DIR / "app_threads.json"


# -------------------------------------------------------------------------
# HUB SETUP DASHBOARD CONFIG
# -------------------------------------------------------------------------
def load_hub_dashboard_config() -> dict:
    if not HUB_DASHBOARD_FILE.exists():
        return {}
    try:
        with open(HUB_DASHBOARD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading hub dashboard config: {e}")
        return {}


def save_hub_dashboard_config(data: dict) -> None:
    try:
        with open(HUB_DASHBOARD_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving hub dashboard config: {e}")


# -------------------------------------------------------------------------
# THREAD SYNC DASHBOARD CONFIG (SEPARATE FROM HUB DASHBOARD)
# -------------------------------------------------------------------------
def load_thread_sync_dashboard_config() -> dict:
    if not THREAD_SYNC_DASHBOARD_FILE.exists():
        return {}
    try:
        with open(THREAD_SYNC_DASHBOARD_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading thread sync dashboard config: {e}")
        return {}


def save_thread_sync_dashboard_config(data: dict) -> None:
    try:
        with open(THREAD_SYNC_DASHBOARD_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving thread sync dashboard config: {e}")


# -------------------------------------------------------------------------
# HUB DEFAULTS, MAPPINGS & DIVISIONS
# -------------------------------------------------------------------------
def load_hub_defaults() -> dict:
    if not HUB_DEFAULTS_FILE.exists():
        return {}
    try:
        with open(HUB_DEFAULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading hub defaults: {e}")
        return {}


def save_hub_defaults(data: dict) -> None:
    try:
        with open(HUB_DEFAULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving hub defaults: {e}")


def load_thread_mappings() -> list[dict]:
    if not THREAD_MAPPINGS_FILE.exists():
        return []
    try:
        with open(THREAD_MAPPINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading thread mappings: {e}")
        return []


def save_thread_mappings(data: list[dict]) -> None:
    try:
        with open(THREAD_MAPPINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving thread mappings: {e}")


def load_division_records() -> list[dict]:
    if not DIVISION_RECORDS_FILE.exists():
        return []
    try:
        with open(DIVISION_RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading division records: {e}")
        return []


def save_division_records(data: list[dict]) -> None:
    try:
        with open(DIVISION_RECORDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving division records: {e}")


# -------------------------------------------------------------------------
# APPLICATION SYSTEM CONFIG & THREAD MAPPINGS
# -------------------------------------------------------------------------
def load_app_config() -> dict:
    if not APP_CONFIG_FILE.exists():
        return {}
    try:
        with open(APP_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading application config: {e}")
        return {}


def save_app_config(data: dict) -> None:
    try:
        with open(APP_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving application config: {e}")


def load_app_threads() -> list[dict]:
    if not APP_THREADS_FILE.exists():
        return []
    try:
        with open(APP_THREADS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading app threads: {e}")
        return []


def save_app_threads(data: list[dict]) -> None:
    try:
        with open(APP_THREADS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving app threads: {e}")