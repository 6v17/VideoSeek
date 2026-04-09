import logging
import os
from logging.handlers import RotatingFileHandler


LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
LOGGER_NAME = "videoseek"


def get_app_data_dir():
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return os.path.join(local_appdata, "VideoSeek")
    return os.path.join(os.path.expanduser("~"), ".videoseek")


def get_log_file():
    return os.path.join(get_app_data_dir(), "logs", "app.log")


def setup_logging(level=logging.INFO):
    root_logger = logging.getLogger(LOGGER_NAME)
    if root_logger.handlers:
        root_logger.setLevel(level)
        return root_logger

    root_logger.setLevel(level)
    root_logger.propagate = False

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    log_file = get_log_file()
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name):
    base_logger = logging.getLogger(LOGGER_NAME)
    if not base_logger.handlers:
        setup_logging()
    return base_logger.getChild(name)
