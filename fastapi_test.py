import time

from src.web.mobile_bridge import MobileBridgeService


def _on_image_received(path, _source):
    print(f"received: {path}")


if __name__ == "__main__":
    service = MobileBridgeService(on_image_received=_on_image_received)
    service.start()
    print(service.get_access_url())
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()
