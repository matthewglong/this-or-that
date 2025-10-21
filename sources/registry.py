import importlib, pkgutil
from typing import Dict, Type, List
from .base import DataSource

_REGISTRY: Dict[str, Type[DataSource]] = {}

def register(cls: Type[DataSource]):
    _REGISTRY[cls.key] = cls
    return cls

def get(key: str) -> Type[DataSource]:
    return _REGISTRY[key]

def list_sources() -> List[Type[DataSource]]:
    return [cls for _, cls in _REGISTRY.items()]

def autoload():
    # Auto-import all modules in the sources package to populate registry
    from . import __path__ as pkg_path  # type: ignore
    for m in pkgutil.iter_modules(pkg_path):
        if not m.ispkg:
            importlib.import_module(f"{__package__}.{m.name}")
