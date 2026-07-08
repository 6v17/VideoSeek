import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

payloads = [
    {"aid": 6383, "service": "www.douyin.com"},
    {"aid": 1128, "service": "www.douyin.com"},
    {"aid": 24, "service": "www.douyin.com"},
]
for payload in payloads:
    body = json.dumps(
        {
            "aid": payload["aid"],
            "needFid": False,
            "region": "cn",
            "service": payload["service"],
            "union": True,
        }
    ).encode()
    req = urllib.request.Request(
        "https://ttwid.bytedance.com/ttwid/union/register/",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        cookies = resp.headers.get_all("Set-Cookie") or []
        print("aid", payload["aid"], "status", resp.status, "cookies", len(cookies))
        for item in cookies:
            print(" ", item.split(";", 1)[0])
