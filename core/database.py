import json
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "thread_mappings.json"

def load_data() -> dict:
    """Loads the entire JSON structure."""
    if not DATA_FILE.exists():
        return {"mappings": [], "dashboard": {"channel_id": None, "message_id": None}}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Migration check: Convert old dict format to list format if needed
            mappings = data.get("mappings", [])
            if isinstance(mappings, dict):
                newList = []
                for role_id, val in mappings.items():
                    if isinstance(val, dict):
                        newList.append({
                            "role_id": int(role_id),
                            "thread_id": val.get("thread_id"),
                            "created_by": val.get("created_by")
                        })
                    else:
                        newList.append({
                            "role_id": int(role_id),
                            "thread_id": val,
                            "created_by": None
                        })
                data["mappings"] = newList
                
            return data
    except (json.JSONDecodeError, OSError):
        return {"mappings": [], "dashboard": {"channel_id": None, "message_id": None}}

def save_data(data: dict) -> None:
    """Saves the entire dictionary to JSON."""
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_thread_mappings() -> list:
    mappings = load_data().get("mappings", [])
    if isinstance(mappings, dict):
        return []
    return mappings

def save_thread_mappings(mappings: list) -> None:
    data = load_data()
    data["mappings"] = mappings
    save_data(data)

def load_dashboard_config() -> dict:
    return load_data().get("dashboard", {"channel_id": None, "message_id": None})

def save_dashboard_config(channel_id: int | None, message_id: int | None = None) -> None:
    data = load_data()
    data["dashboard"] = {
        "channel_id": channel_id,
        "message_id": message_id
    }
    save_data(data)