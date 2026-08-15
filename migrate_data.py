import os
import json
import shutil

# Your main server ID
GUILD_ID = "531243268256694313"
DATA_DIR = "data"
NEW_DIR = os.path.join(DATA_DIR, GUILD_ID)

# Create the new guild directory
os.makedirs(NEW_DIR, exist_ok=True)

# Files that just need to be moved directly into the new folder
FLAT_FILES = [
    "app_threads.json",
    "casual_records.json",
    "division_records.json",
    "hub_dashboard.json",
    "hub_defaults.json",
    "legacy_division_records.json",
    "thread_mappings.json",
    "thread_sync_dashboard.json"
]

# Files that need their top-level Guild ID wrapper removed
WRAPPED_FILES = [
    "app_config.json",
    "bait_stats.json",
    "dynamic_voice_config.json",
    "rank_system_config.json",
    "role_sync_config.json"
]

print("Starting data migration...\n")

for filename in FLAT_FILES:
    old_path = os.path.join(DATA_DIR, filename)
    new_path = os.path.join(NEW_DIR, filename)
    if os.path.exists(old_path):
        shutil.move(old_path, new_path)
        print(f"✅ Moved: {filename}")

for filename in WRAPPED_FILES:
    old_path = os.path.join(DATA_DIR, filename)
    new_path = os.path.join(NEW_DIR, filename)
    if os.path.exists(old_path):
        with open(old_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                data = {}
        
        # Extract just your main server's data, removing the wrapper
        guild_data = data.get(GUILD_ID, {})
        
        # Save it to the new folder
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(guild_data, f, indent=4)
            
        print(f"✅ Unwrapped and Moved: {filename}")
        
        # Delete the old wrapped file
        os.remove(old_path)

print("\n🎉 Migration complete! You can delete migrate_data.py now.")