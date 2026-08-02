import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "thread_mappings.json"

def load_data() -> dict:
    """Loads the entire JSON structure."""
    if not DATA_FILE.exists():
        return {"mappings": {}, "dashboard": {"channel_id": None, "message_id": None}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "mappings" not in data:
                data = {"mappings": data, "dashboard": {"channel_id": None, "message_id": None}}
            return data
    except (json.JSONDecodeError, OSError):
        return {"mappings": {}, "dashboard": {"channel_id": None, "message_id": None}}

def save_data(data: dict) -> None:
    """Saves the entire dictionary to JSON."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_thread_mappings() -> dict:
    return load_data().get("mappings", {})

def save_thread_mappings(mappings: dict) -> None:
    data = load_data()
    data["mappings"] = mappings
    save_data(data)

def load_dashboard_config() -> dict:
    return load_data().get("dashboard", {"channel_id": None, "message_id": None})

def save_dashboard_config(channel_id: int, message_id: int | None = None) -> None:
    data = load_data()
    data["dashboard"] = {
        "channel_id": channel_id,
        "message_id": message_id
    }
    save_data(data)