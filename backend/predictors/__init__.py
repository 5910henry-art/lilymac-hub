# predictors/__init__.py
from importlib import import_module

# Simple cache to avoid repeated imports
_predictor_cache = {}

async def get_predictor(version: str):
    """
    Dynamically load predictor module by model_version.
    Example: version='v11a' → imports predictors.v11a
    Caches loaded modules for efficiency.
    """
    if version in _predictor_cache:
        return _predictor_cache[version]
    
    module_name = f"predictors.{version}"
    module = import_module(module_name)
    _predictor_cache[version] = module
    return module
