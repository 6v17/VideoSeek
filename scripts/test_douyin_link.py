import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.remote_link_precheck_service import (
    classify_remote_link,
    normalize_link_input,
    precheck_remote_links,
)
from src.services.video_download_service import parse_links_from_text

text = (
    "4.10 oda:/ 09/24 M@w.FU :7pm 爱情公寓｜第三季｜第258集  "
    "https://v.douyin.com/osId0ScbU80/ 复制此链接，打开Dou音搜索，直接观看视频！"
)
print("normalized:", normalize_link_input(text))
print("links:", parse_links_from_text(text))
print("precheck:", precheck_remote_links(parse_links_from_text(text)))
print("classify:", classify_remote_link("https://v.douyin.com/osId0ScbU80/"))
