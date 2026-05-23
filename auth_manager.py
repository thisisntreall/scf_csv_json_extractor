import getpass
import re
from pathlib import Path
from typing import Optional

try:
    from logging_config import get_logger
    from constants import ENV_SUPABASE_URL, ENV_SUPABASE_KEY, ENV_NEON_DATABASE_URL
    logger = get_logger(__name__)
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    ENV_SUPABASE_URL = "SUPABASE_URL"
    ENV_SUPABASE_KEY = "SUPABASE_SERVICE_KEY"
    ENV_NEON_DATABASE_URL = "NEON_DATABASE_URL"

ENV_FILE = Path(__file__).parent.resolve() / ".env"


def _read_env() -> dict[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _write_env(env: dict[str, str]) -> None:
    lines = []
    for key, value in env.items():
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
    logger.info(f"Credentials saved to {ENV_FILE}")


def login_supabase() -> None:
    env = _read_env()
    print("\n--- Supabase Login ---")
    print("You can find these in your Supabase project: Settings > API\n")
    url = input("Project URL (e.g. https://xxx.supabase.co): ").strip()
    key = getpass.getpass("Service Role Key: ").strip()

    if not url or not key:
        print("Error: Both URL and key are required.")
        return

    env[ENV_SUPABASE_URL] = url
    env[ENV_SUPABASE_KEY] = key
    _write_env(env)
    print("Supabase credentials saved. You can now use --format supabase")


def login_neon() -> None:
    env = _read_env()
    print("\n--- Neon Login ---")
    print("You can find your connection string in the Neon console dashboard.\n")
    conn_str = getpass.getpass("Connection string (postgresql://...): ").strip()

    if not conn_str:
        print("Error: Connection string is required.")
        return

    if not conn_str.startswith("postgresql://") and not conn_str.startswith("postgres://"):
        print("Error: Connection string must start with postgresql:// or postgres://")
        return

    env[ENV_NEON_DATABASE_URL] = conn_str
    _write_env(env)
    print("Neon credentials saved. You can now use --format neon")


def get_supabase_dsn() -> Optional[str]:
    env = _read_env()
    url = env.get(ENV_SUPABASE_URL)
    key = env.get(ENV_SUPABASE_KEY)
    if not url or not key:
        return None
    match = re.match(r"https://([^.]+)\.supabase\.co", url)
    if not match:
        logger.error(f"Could not parse Supabase URL: {url}")
        return None
    project_ref = match.group(1)
    return f"postgresql://postgres.{project_ref}:{key}@aws-0-us-east-1.pooler.supabase.com:6543/postgres"


def get_neon_dsn() -> Optional[str]:
    env = _read_env()
    return env.get(ENV_NEON_DATABASE_URL)
