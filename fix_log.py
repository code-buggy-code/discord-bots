import json
import os
import urllib.request

# 1. Load the Token
try:
    from BuggyBot.secret_bot import TOKEN
    print("✅ Found Token.")
except:
    print("❌ Error: Could not find BuggyBot/secret_bot.py")
    exit()

# 2. Who am I? (Check the Bot Identity)
print("🔎 Checking Bot Identity...")
req = urllib.request.Request("https://discord.com/api/v9/users/@me", headers={"Authorization": f"Bot {TOKEN}"})
try:
    with urllib.request.urlopen(req) as response:
        data = json.load(response)
        print(f"🤖 I am logged in as: {data['username']}#{data['discriminator']}")
        print(f"🆔 My Bot ID is: {data['id']}")
except urllib.error.HTTPError as e:
    print(f"❌ Token Error: {e}")
    exit()

# 3. Where am I sending logs? (Check Database)
db_path = os.path.join("BuggyBot", "database.json")
target_channel = None

if os.path.exists(db_path):
    with open(db_path, "r") as f:
        db_data = json.load(f)
    
    config_list = db_data.get("bot_config", [])
    for doc in config_list:
        if doc.get("_id") == "config":
            target_channel = doc.get("log_channel_id")
            break

print(f"📂 Database says Log Channel ID is: {target_channel}")

# 4. Test the Connection
if target_channel:
    print(f"📨 Trying to send a test message to {target_channel}...")
    url = f"https://discord.com/api/v9/channels/{target_channel}/messages"
    headers = {"Authorization": f"Bot {TOKEN}", "Content-Type": "application/json"}
    data = {"content": "🔍 Detective Test Message"}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
        urllib.request.urlopen(req)
        print("✅ SUCCESS! Message sent. The Manager should work now.")
    except urllib.error.HTTPError as e:
        print(f"❌ FAILED: {e}")
        if e.code == 403:
            print("💡 TIP: Error 403 means 'Forbidden'.")
            print("   1. Check if the Channel ID above is correct.")
            print("   2. Check if the Bot User (listed above) is actually in that server.")
        if e.code == 404:
            print("💡 TIP: Error 404 means 'Not Found'. That Channel ID does not exist!")
else:
    print("❌ No Log Channel ID found in database!")
