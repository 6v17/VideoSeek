import json
import urllib.request

url = "https://www.douyin.com/"
req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.douyin.com/",
    },
)
with urllib.request.urlopen(req, timeout=30) as resp:
    cookies = resp.headers.get_all("Set-Cookie") or []
    print("status", resp.status)
    for item in cookies:
        print(item.split(";", 1)[0])
