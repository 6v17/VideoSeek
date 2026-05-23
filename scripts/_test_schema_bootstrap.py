from src.app.config import load_config
from src.storage.config_store import get_config_schema_version, get_active_model_profile
from src.storage.migration_runner import ensure_config_schema_v2_bootstrap

c = load_config()
print("before", get_config_schema_version(c))
print("profile", get_active_model_profile(c)["id"])
ensure_config_schema_v2_bootstrap()
c2 = load_config()
print("after", get_config_schema_version(c2), get_active_model_profile(c2)["id"])
