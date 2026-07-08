from src.app.app_meta import get_app_meta


def get_donate_payload():
    meta = get_app_meta()
    image_url = str(meta.get("donate_image_url", "") or "").strip()
    github_url = str(meta.get("donate_github_url", "") or "https://github.com/6v17/VideoSeek").strip()
    bilibili_url = str(meta.get("donate_bilibili_url", "") or "https://space.bilibili.com/473427924").strip()
    qq_url = str(meta.get("donate_qq_url", "") or "").strip()
    return {
        "image_url": image_url,
        "github_url": github_url,
        "bilibili_url": bilibili_url,
        "qq_url": qq_url,
    }
