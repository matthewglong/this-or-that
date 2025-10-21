from typing import Optional, Dict, Any, List

class DataSource:
    key: str         # machine key, e.g. "upload"
    label: str       # UI label, e.g. "Upload"

    @classmethod
    def form_fields(cls) -> List[Dict[str, Any]]:
        """Describe fields for the homepage per slot for this source.
        Each dict supports:
          - key:     string appended to 'channel{idx}_<key>' as the field name
          - type:    'file' | 'text'
          - label:   visible label (optional)
          - placeholder: optional (for text)
          - help:    small help text (optional)
          - folder:  bool — if True on 'file', use folder upload (webkitdirectory)
          - required: bool — used to enable Start button
        """
        return []

    def build_channel(self, *, gid: str, idx: int, form: Any, files: Any) -> Optional[Dict]:
        """Return a channel dict: {"name": str, "dir": Optional[str], "images": [str], "source": str}
        or None if input invalid/incomplete.
        """
        raise NotImplementedError
