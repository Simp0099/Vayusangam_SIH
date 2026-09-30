from .base import ModelProvider


class NCUMProviderStub(ModelProvider):
    def rollout(self, fire_reduction: float = 0):
        raise NotImplementedError("Planned adapter: NCUM is not configured in this prototype.")
