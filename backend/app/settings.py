import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path("/tmp/llmspindle-data") if os.getenv("VERCEL") else BASE_DIR / "data"
DATA_DIR = Path(os.getenv("DATA_DIR", DEFAULT_DATA_DIR)).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
ANNOTATION_FILE = DATA_DIR / "annotations.json"
SLEEP_EPOCH_FILE = DATA_DIR / "sleep_epochs.json"
JOB_FILE = DATA_DIR / "analysis_jobs.json"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini")
OPENAI_PROMPT_ID = os.getenv("OPENAI_PROMPT_ID", "")
OPENAI_PROMPT_VERSION = os.getenv("OPENAI_PROMPT_VERSION", "1")
MAX_RENDER_SECONDS = float(os.getenv("MAX_RENDER_SECONDS", "120"))
MAX_WINDOW_POINTS = 6000
DEFAULT_CHANNEL_LIMIT = 12
LLM_REVIEW_WORKERS = max(1, int(os.getenv("LLM_REVIEW_WORKERS", "3")))

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MPLCONFIG_DIR = DATA_DIR / "matplotlib"
XDG_CACHE_DIR = DATA_DIR / "cache"
MPLCONFIG_DIR.mkdir(parents=True, exist_ok=True)
XDG_CACHE_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "numba-cache").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPLCONFIG_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(XDG_CACHE_DIR))
os.environ.setdefault("MNE_DONTWRITE_HOME", "true")
os.environ.setdefault("NUMBA_CACHE_DIR", str(DATA_DIR / "numba-cache"))
if not ANNOTATION_FILE.exists():
    ANNOTATION_FILE.write_text("[]", encoding="utf-8")
if not SLEEP_EPOCH_FILE.exists():
    SLEEP_EPOCH_FILE.write_text("[]", encoding="utf-8")
if not JOB_FILE.exists():
    JOB_FILE.write_text("[]", encoding="utf-8")
