"""Protocol fixture only. No model dependencies or network calls."""
import json
import os
import sys
import time

print(json.dumps({"type": "ready", "device": "cpu"}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request["audioPath"].endswith("hang.wav"):
        time.sleep(60)
    if request["audioPath"].endswith("crash.wav"):
        print("fixture crash", file=sys.stderr, flush=True)
        sys.exit(3)
    print(json.dumps({"type": "result", "id": request["id"], "response": {
        "text": "Chișinău. Проверка.", "pid": os.getpid(), "options": request["options"],
    }}), flush=True)
