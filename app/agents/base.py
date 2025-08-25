from typing import Any, Dict, List


class Provider:
    def __init__(self) -> None:
        pass

    async def __call__(self, prompt: str, **kwargs: Any) -> str:
        raise NotImplementedError()


class EmbeddingProvider:
    async def embed(self, text: str) -> List[float]:
        raise NotImplementedError()
