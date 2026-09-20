"""
config.py

Loads settings from a .env file (if there is one) into environment variables.
Import this FIRST in any script that connects to the database:

    import config  # loads .env

The scripts then read DB_HOST, DB_USER, DB_PASSWORD and DB_NAME with
os.environ.get(...). If there is no .env file, or python-dotenv is not
installed, they fall back to local defaults, so nothing breaks.
"""

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed: use the defaults in each script
