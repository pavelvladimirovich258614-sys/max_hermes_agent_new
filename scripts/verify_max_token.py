#!/usr/bin/env python3
"""Verify MAX bot token by calling /me endpoint."""
import os, sys, json, urllib.request, urllib.error

def get_token():
    token = os.environ.get("MAX_BOT_TOKEN", "")
    if token and not token.startswith("PASTE"):
        return token
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("MAX_BOT_TOKEN=") and "#" not in line.split("=")[0]:
                    val = line.split("=", 1)[1].strip().strip("\'").strip('"')
                    if val and not val.startswith("PASTE"):
                        return val
    return None

def main():
    token = get_token()
    if not token:
        print("ERROR: MAX_BOT_TOKEN not found in env or ~/.hermes/.env")
        sys.exit(1)
    url = "https://platform-api.max.ru/me"
    req = urllib.request.Request(url)
    # MAX API expects the raw token in Authorization, without "Bearer"
    req.add_header("Authorization", token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print("Token valid!")
        print(f"  Bot ID:       {data.get('user_id', data.get('id', 'N/A'))}")
        print(f"  Bot name:     {data.get('name', 'N/A')}")
        print(f"  Bot username: {data.get('username', 'N/A')}")
        print(f"  Is bot:       {data.get('is_bot', 'N/A')}")
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
