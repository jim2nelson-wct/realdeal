import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

INSTANCE_DIR = BASE_DIR / "instance"
UPLOAD_DIR = BASE_DIR / "uploads"
JOBS_DIR = BASE_DIR / "jobs"

HOTFOLDERS = {
    "1": os.environ.get("SOFRIP_HOTFOLDER_1", r"C:\hotfolders\unit1"),
    "2": os.environ.get("SOFRIP_HOTFOLDER_2", r"C:\hotfolders\unit2"),
    "3": os.environ.get("SOFRIP_HOTFOLDER_3", r"C:\hotfolders\unit3"),
    "4": os.environ.get("SOFRIP_HOTFOLDER_4", r"C:\hotfolders\unit4"),
}

ALLOWED_EXTENSIONS = {
    ".pdf", ".ps", ".eps", ".tiff", ".tif", ".jpg", ".jpeg", ".png",
    ".bmp", ".gif", ".psd",
}

RASTER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".psd"}

SQLALCHEMY_DATABASE_URI = f"sqlite:///{INSTANCE_DIR / 'realdeal.db'}"

HOTXML_LOG = os.environ.get("SOFRIP_HOTXML_LOG", r"C:\WasatchSoftRIP\hotxml.log")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-change-me")
