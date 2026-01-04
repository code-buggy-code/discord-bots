import os
import time
import subprocess
import sys
import datetime
import json

# --- FUNCTIONS IN THIS FILE ---
# 1. log(message) - Prints timestamped logs.
# 2. queue_discord_msg(content) - Sends messages to the Discord bot queue.
# 3. get_git_hash() - Gets the current commit hash of the repo.
# 4. stop_all_bots() - Forcefully stops all bot processes.
# 5. start_all_bots() - Finds and starts all main.py files.
# 6. check_and_update_github() - Pulls from GitHub and returns True if code changed.
# ------------------------------

# --- CONFIGURATION ---
DAILY_REPORT_HOUR = 4 # 4 AM
# ---------------------

ROOT_DIR = "/home/ubuntu/GitHub"
sys.path.append(ROOT_DIR)

# Path to the shared "Mailbox" file
IPC_FILE = os.path.join(ROOT_DIR, "BuggyBot", "pending_logs.json")

def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}")

def queue_discord_msg(content):
    queue = []
    if os.path.exists(IPC_FILE):
        try:
            with open(IPC_FILE, "r") as f:
                queue = json.load(f)
        except: queue = []
    
    queue.append(content)
    
    with open(IPC_FILE, "w") as f:
        json.dump(queue, f)

def get_git_hash():
    """Returns the current Git Commit Hash."""
    os.chdir(ROOT_DIR)
    return subprocess.getoutput("git rev-parse HEAD")

def stop_all_bots():
    """Kills all running bots."""
    log("🛑 Stopping all bots...")
    os.system("pkill -f main.py")
    time.sleep(2) # Give them a moment to die

def start_all_bots():
    """Scans for main.py files and starts them if they aren't running."""
    active_bots = []
    
    for item in os.listdir(ROOT_DIR):
        folder_path = os.path.join(ROOT_DIR, item)
        
        # We only care about folders with "main.py"
        if os.path.isdir(folder_path) and "main.py" in os.listdir(folder_path):
            script_path = os.path.join(folder_path, "main.py")
            
            # Check if it is running
            is_running = subprocess.getoutput(f"ps -ef | grep '{script_path}' | grep -v grep")
            
            if not is_running:
                log(f"⚡ Starting {item}...")
                os.chdir(folder_path)
                os.system(f"nohup python3 {script_path} > ../{item}.log 2>&1 &")
                os.chdir(ROOT_DIR)
            
            active_bots.append(item)
    
    return active_bots

def check_and_update_github():
    """Checks for updates on GitHub. Returns True if updates were applied."""
    current_hash = get_git_hash()
    
    # Fetch the latest info from GitHub without merging yet
    os.chdir(ROOT_DIR)
    subprocess.getoutput("git fetch")
    
    # Check what the hash WOULD be if we pulled (remote/main)
    # Note: Assuming 'origin/main' is the branch. If you use 'master', change 'main' to 'master'.
    remote_hash = subprocess.getoutput("git rev-parse origin/main")
    
    if current_hash != remote_hash:
        log("🔄 New code found on GitHub! Updating...")
        # Force the update
        os.system("git pull")
        return True
        
    return False

# --- MAIN LOOP ---
if __name__ == "__main__":
    log("✅ Smart Manager Started in GitHub-Sync Mode.")
    
    # Initial cleanup and start
    stop_all_bots()
    bots = start_all_bots()
    queue_discord_msg(f"👀 **Manager Online:** Synced with GitHub and running!")
    
    last_report_date = None

    while True:
        try:
            # 1. Check for GitHub Updates
            if check_and_update_github():
                log("🚀 Update applied! Restarting everything...")
                stop_all_bots() # Kill the old versions
                bots = start_all_bots() # Start the new versions
                queue_discord_msg("♻️ **System Updated:** All bots have been restarted with the latest code from GitHub.")

            # 2. Keep bots alive (Crash recovery)
            # Even if no update, we run start_all_bots to ensure nothing crashed.
            bots = start_all_bots()

            # 3. Daily Report
            now = datetime.datetime.now()
            if now.hour == DAILY_REPORT_HOUR and last_report_date != now.date():
                status_msg = f"Good morning! \nTime: {now.strftime('%c')}\nActive Bots: {len(bots)}\nGitHub Sync is active."
                queue_discord_msg(status_msg)
                last_report_date = now.date()
                
        except Exception as e:
            log(f"⚠️ Manager Error: {e}")
        
        time.sleep(10) # Check GitHub every 10 seconds
