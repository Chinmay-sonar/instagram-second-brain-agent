import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(BASE_DIR / ".env")

# Telegram Bot
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ALLOWED_USER_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "").strip()

# Obsidian Vault Path
OBSIDIAN_VAULT_PATH = Path(os.getenv("OBSIDIAN_VAULT_PATH", str(BASE_DIR / "The Extractor"))).resolve()

# AI Brain API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
MOONSHOT_NVIDIA_KEY = os.getenv("MOONSHOT_NVIDIA_KEY", "").strip()

# Instagram Session ID
INSTAGRAM_SESSION_ID = os.getenv("INSTAGRAM_SESSION_ID", "").strip()

# Temp directory for media
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# Standard Categories for Obsidian organization (clean folder names for Windows compatibility)
CATEGORIES = {
    "UI-UX": "UI-UX & Design",
    "Internships": "Internships & Opportunities",
    "Hackathons": "Hackathons & Contests",
    "AI-Agents": "AI & Agent Frameworks",
    "Roadmaps": "Roadmaps & Learning",
    "Dev-Tools": "Dev Tools & Utilities"
}

def set_allowed_telegram_user(user_id: int):
    """Persist the allowed user ID to .env file upon first /start pairing."""
    global TELEGRAM_ALLOWED_USER_ID
    TELEGRAM_ALLOWED_USER_ID = str(user_id)
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        if "TELEGRAM_ALLOWED_USER_ID=" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("TELEGRAM_ALLOWED_USER_ID="):
                    new_lines.append(f"TELEGRAM_ALLOWED_USER_ID={user_id}")
                else:
                    new_lines.append(line)
            env_file.write_text("\n".join(new_lines), encoding="utf-8")
        else:
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f"\nTELEGRAM_ALLOWED_USER_ID={user_id}\n")

def set_instagram_session_id(session_id: str):
    """Persist the new Instagram session ID to .env file."""
    global INSTAGRAM_SESSION_ID
    clean_id = str(session_id).strip().strip('"\'')
    INSTAGRAM_SESSION_ID = clean_id
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        if "INSTAGRAM_SESSION_ID=" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("INSTAGRAM_SESSION_ID="):
                    new_lines.append(f'INSTAGRAM_SESSION_ID="{clean_id}"')
                else:
                    new_lines.append(line)
            env_file.write_text("\n".join(new_lines), encoding="utf-8")
        else:
            with open(env_file, "a", encoding="utf-8") as f:
                f.write(f'\nINSTAGRAM_SESSION_ID="{clean_id}"\n')

