"""子系统 5：因子库管理层。"""

from reproagent.library.classifier import StyleClassifier
from reproagent.library.manager import FactorLibraryManager
from reproagent.library.protocol import FactorLibraryProtocol
from reproagent.library.versioning import bump, compute_dedup_hash

__all__ = [
    "FactorLibraryManager",
    "FactorLibraryProtocol",
    "StyleClassifier",
    "bump",
    "compute_dedup_hash",
]
