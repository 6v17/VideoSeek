import json
import re
import urllib.request

body = json.dumps(
    {
        "aid": 6383,
        "needFid": False,
        "region": "cn",
        "service": "www.douyin.com",
        "union": True,
    }
).encode()
req = urllib.request.Request(
    "https://ttwid.bytedance.com/ttwid/union/register/",
    data=body,
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(req, timeout=30) as resp:
    ttwid_raw = ""
    for item in resp.headers.get_all("Set-Cookie") or []:
        if item.startswith("ttwid="):
            ttwid_raw = item.split(";", 1)[0]
    print("ttwid header", ttwid_raw[:80])

video_url = "https://www.douyin.com/video/7624728705768153193"
req2 = urllib.request.Request(
    video_url,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
        "Cookie": ttwid_raw,
    },
)
with urllib.request.urlopen(req2, timeout=30) as resp:
    html = resp.read().decode("utf-8", errors="ignore")
    print("status", resp.status, "len", len(html))
    for item in resp.headers.get_all("Set-Cookie") or []:
        print("set-cookie", item.split(";", 1)[0][:120])
    for key in ("s_v_web_id", "msToken", "ttwid", "__ac_nonce"):
        if key in html:
            print("found in html", key)
    match = re.search(r"s_v_web_id[=:\"']+([A-Za-z0-9_-]+)", html)
    if match:
        print("s_v_web_id match", match.group(1))
