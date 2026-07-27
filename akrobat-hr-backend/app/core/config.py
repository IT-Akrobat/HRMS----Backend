import os

from dotenv import load_dotenv

load_dotenv()


def get_env(key: str, default: str | None = None):
    value = os.getenv(key, default)

    if value is None:
        raise ValueError(f"Missing environment variable: {key}")

    return value


SUPABASE_URL = get_env("SUPABASE_URL")

SUPABASE_ANON_KEY = get_env("SUPABASE_ANON_KEY")

SUPABASE_SERVICE_ROLE_KEY = get_env("SUPABASE_SERVICE_ROLE_KEY")

SUPABASE_JWT_SECRET = get_env("SUPABASE_JWT_SECRET")

APP_NAME = os.getenv("APP_NAME", "Akrobat HRMS")

APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# ---------------------------------------------------------------------
# Quote of the Day (see app/dashboard/services.get_quote_of_day)
# ---------------------------------------------------------------------
# Both optional and intentionally read with os.getenv (not get_env()):
# get_env() raises and kills app startup if the var is missing, but this
# feature is designed to degrade gracefully (curated fallback content)
# rather than take the whole API down when a key isn't configured yet.

# Public, keyless random-quote API. Swap via env if it ever goes down.
QUOTE_API_URL = os.getenv("QUOTE_API_URL", "https://zenquotes.io/api/random")

# Pexels image search (https://www.pexels.com/api/) — free API key.
# Background images fall back to a curated static list when unset.
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PEXELS_SEARCH_QUERY = os.getenv(
    "PEXELS_SEARCH_QUERY", "workplace safety construction teamwork"
)
