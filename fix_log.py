import json
import os

# --- PASTE YOUR LOG CHANNEL ID HERE ---
NEW_LOG_CHANNEL_ID = 1434622477660717056  # <--- REPLACE THIS NUMBER!

# Path to BuggyBot's database
db_path = os.path.join("BuggyBot", "database.json")

if os.path.exists(db_path):
    with open(db_path, "r") as f:
        data = json.load(f)

    # Find the config section
    config_list = data.get("bot_config", [])
    found = False
    
    for doc in config_list:
        if doc.get("_id") == "config":
            old_id = doc.get("log_channel_id", "Unknown")
            print(f"Found old Log Channel ID: {old_id}")
            
            # Update it
            doc["log_channel_id"] = NEW_LOG_CHANNEL_ID
            found = True
            break
    
    if not found:
        print("Config not found, creating new entry...")
        config_list.append({"_id": "config", "log_channel_id": NEW_LOG_CHANNEL_ID})
        data["bot_config"] = config_list

    # Save back to file
    with open(db_path, "w") as f:
        json.dump(data, f, indent=4, default=str)
    
    print(f"✅ SUCCESS! Log Channel updated to: {NEW_LOG_CHANNEL_ID}")
else:
    print(f"❌ Error: Could not find {db_path}")
