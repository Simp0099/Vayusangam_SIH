from abc import ABC, abstractmethod
from typing import Any


class ModelProvider(ABC):
    @abstractmethod
    def rollout(self, fire_reduction: float = 0) -> dict[str, Any]: ...
