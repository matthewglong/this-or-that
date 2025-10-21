import os
from pathlib import Path
from typing import Optional, Dict, Any, List
from .base import DataSource
from .registry import register

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

def _allowed(fpath: str) -> bool:
    return Path(fpath).suffix.lower() in ALLOWED_EXT

@register
class UploadSource(DataSource):
    key = "upload"
    label = "Upload"

    @classmethod
    def form_fields(cls) -> List[Dict[str, Any]]:
        return [
            {
                "key": "test",
                "type": "text",
                "label": "Jondization",
                "placeholder": "Enter jondization",
                "help": "Will fetch 3 test images using your jondization.",
                "required": True
            }
        ]

    @classmethod
    def form_fields(cls) -> List[Dict[str, Any]]:
        return [
            {
                "key": "upload",
                "type": "file",
                "label": "Folder",
                "help": "Choose a folder of images",
                "folder": True,       # enables folder selection (webkitdirectory)
                "required": True
            }
        ]

    def build_channel(self, *, gid: str, idx: int, form: Any, files: Any) -> Optional[Dict]:
        upload_key = f"channel{idx}_upload"
        file_list = files.getlist(upload_key)

        if not file_list:
            return None

        # Infer channel name from first file's path (webkitdirectory)
        first = file_list[0]
        rel = first.filename or ""
        folder_name = rel.split("/")[0].split("\\")[0] if ("/" in rel or "\\" in rel) else Path(rel).stem
        channel_name = "".join(ch for ch in folder_name if ch.isalnum() or ch in (" ", "_", "-", ".")).strip() or f"Upload {idx+1}"

        # Save under uploads/<gid>/<channel_name>
        project_root = Path(__file__).resolve().parents[1]
        ch_dir = project_root / "uploads" / gid / channel_name
        ch_dir.mkdir(parents=True, exist_ok=True)

        saved_any = False
        for f in file_list:
            if not (f and f.filename and _allowed(f.filename)):
                continue
            parts = f.filename.split("/")
            parts = parts[1:] if len(parts) > 1 else [Path(f.filename).name]
            dest_dir = ch_dir
            if len(parts) > 1:
                dest_dir = ch_dir / Path(*parts[:-1])
                dest_dir.mkdir(parents=True, exist_ok=True)
            (dest_dir / Path(parts[-1])).write_bytes(f.read())
            saved_any = True

        if not saved_any:
            return None

        images = []
        for root, _, fs in os.walk(ch_dir):
            for name in fs:
                if _allowed(name):
                    images.append(str(Path(root, name).relative_to(ch_dir)))
        images.sort()
        if not images:
            return None

        return {"name": channel_name, "dir": str(ch_dir), "images": images, "source": self.key}
