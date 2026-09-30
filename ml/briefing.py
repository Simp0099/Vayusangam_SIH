from abc import ABC, abstractmethod


class BriefingProvider(ABC):
    @abstractmethod
    def generate(self, drivers: dict[str, float]) -> str: ...


class TemplateBriefingProvider(BriefingProvider):
    def generate(self, drivers):
        top = sorted(drivers, key=drivers.get, reverse=True)[:3]
        names = {"inversion": "inversion strength", "ventilation": "low ventilation", "smoke": "relative smoke influence"}
        return "AQI is expected to change as ventilation and inversion evolve. Relative smoke transport also contributes to projected PM2.5 in this replay scenario. Primary drivers: " + ", ".join(names.get(x, x) for x in top) + "."


class ClaudeBriefingProvider(BriefingProvider):
    def generate(self, drivers):
        raise NotImplementedError("Optional LLM adapter; deterministic TemplateBriefingProvider remains available.")
