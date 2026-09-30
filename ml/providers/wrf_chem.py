from .base import ModelProvider


class WRFChemProviderStub(ModelProvider):
    def rollout(self, fire_reduction: float = 0):
        raise NotImplementedError("Planned adapter: operational WRF-Chem is not configured in this prototype.")
