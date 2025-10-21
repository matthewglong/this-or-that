from typing import Optional, Dict, Any, List
from .base import DataSource
from .registry import register

@register
class TestSource(DataSource):
    key = "test"
    label = "Test"

    @classmethod
    def form_fields(cls) -> List[Dict[str, Any]]:
        return [{
            "key": "test",
            "type": "text",
            "label": "Jondization",
            "placeholder": "Enter jondization",
            "help": "Will fetch 3 test images using your jondization.",
            "required": True
        }]

    def build_channel(self, *, gid: str, idx: int, form, files) -> Optional[Dict]:
        field = f"channel{idx}_test"
        j = (form.get(field, "") or "").strip()
        name = "".join(ch for ch in j if ch.isalnum() or ch in (" ", "_", "-", ".")).strip() or f"Test {idx+1}"
        urls = [
            f"https://upload.wikimedia.org/wikipedia/commons/e/e8/View_on_Gyakar_%28edited%29.jpg?{j}",
            f"https://upload.wikimedia.org/wikipedia/commons/1/14/Animal_diversity.png?{j}",
            f"https://upload.wikimedia.org/wikipedia/commons/2/20/Albertorainforecast2018.png?{j}",
        ]
        return {"name": name, "dir": None, "images": urls, "source": self.key}
