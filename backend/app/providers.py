"""Normalized provider interfaces; only deterministic demo adapters are enabled by default."""
from abc import ABC, abstractmethod
from typing import Any


class WeatherProvider(ABC):
    @abstractmethod
    async def forecast(self, *args, **kwargs) -> dict[str, Any]: ...


class DemoWeatherProvider(WeatherProvider):
    async def forecast(self, *args, **kwargs):
        return {"status": "DEMO", "source": "deterministic surrogate", "hours": 72, "fields": ["temperature", "wind", "pblh", "radiation"]}


class OpenMeteoProvider(WeatherProvider):
    async def forecast(self, *args, **kwargs):
        raise NotImplementedError("Configure a live NWP adapter before use; replay remains the default.")


class NCUMProvider(WeatherProvider):
    async def forecast(self, *args, **kwargs):
        raise NotImplementedError("NCUM adapter planned; no government forecast feed is connected.")


class FireProvider(ABC):
    @abstractmethod
    async def detections(self, *args, **kwargs) -> dict[str, Any]: ...


class DemoFireProvider(FireProvider):
    async def detections(self, *args, **kwargs):
        from .engine import FIRE_SEEDS
        return {"status": "DEMO / REPLAY DATA", "fires": FIRE_SEEDS}


class FIRMSProvider(FireProvider):
    async def detections(self, *args, **kwargs):
        raise NotImplementedError("NASA FIRMS adapter planned; no live fire detections are claimed.")


class CAMSProvider:
    async def forecast(self, *args, **kwargs):
        raise NotImplementedError("CAMS adapter planned; no CAMS forecast data is connected.")


class ERA5Provider:
    async def reanalysis(self, *args, **kwargs):
        raise NotImplementedError("ERA5 adapter planned; no reanalysis data is connected.")


class ObservationProvider(ABC):
    @abstractmethod
    async def observations(self, *args, **kwargs) -> dict[str, Any]: ...


class DemoObservationProvider(ObservationProvider):
    async def observations(self, *args, **kwargs):
        return {"status": "DEMO / REPLAY DATA", "observations": []}


class CPCBOpenAQProvider(ObservationProvider):
    async def observations(self, *args, **kwargs):
        raise NotImplementedError("CPCB/OpenAQ adapter planned; connect verified observations for evaluation.")
