import os
import logging
from typing import Any, Dict, List
from fastapi.concurrency import run_in_threadpool

from groq import Groq
from sentence_transformers import SentenceTransformer

from ..agents.exceptions import ProviderError
from .base import Provider, EmbeddingProvider

logger = logging.getLogger(__name__)


class GroqProvider(Provider):
    def __init__(self, api_key: str | None = None, model: str = "llama-3.3-70b-versatile"):
        api_key = api_key or os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ProviderError("Groq API key is missing")
        self._client = Groq(api_key=api_key)
        self.model = model

    def _generate_sync(self, prompt: str, options: Dict[str, Any]) -> str:
        logger.info(f"Generating response with Groq model: {self.model}")
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ],
                **options,
            )
            print("äpi",response.choices[0].message.content)
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq generation error: {e}")
            raise ProviderError(f"Groq - error generating response: {e}") from e

    async def __call__(self, prompt: str, **generation_args: Any) -> str:
        opts = {
            "temperature": generation_args.get("temperature", 0),
            "top_p": generation_args.get("top_p", 0.9),
            "max_tokens": generation_args.get("max_length", 20000),
        }
        return await run_in_threadpool(self._generate_sync, prompt, opts)


class GroqEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        api_key: str | None = None,
        embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        """
        Groq doesn't provide embeddings directly, so we use sentence-transformers
        locally for fast and reliable embeddings.
        """
        self._model_name = embedding_model
        self._model = None  # Lazy load the model
        logger.info(f"Initialized GroqEmbeddingProvider with model: {embedding_model}")

    def _load_model(self):
        """Lazy load the sentence transformer model"""
        if self._model is None:
            logger.info(f"Loading sentence transformer model: {self._model_name}")
            try:
                self._model = SentenceTransformer(self._model_name, trust_remote_code=True)
                logger.info(f"Successfully loaded model: {self._model_name}")
            except Exception as e:
                logger.error(f"Failed to load model {self._model_name}: {e}")
                raise ProviderError(f"Failed to load embedding model: {e}")
        return self._model

    def _embed_sync(self, text: str) -> List[float]:
        """
        Generate embeddings using sentence-transformers locally
        """
        try:
            model = self._load_model()
            # Generate embedding for single text
            embedding = model.encode([text], convert_to_numpy=True)
            # Return as a list of floats
            return embedding[0].tolist()
        except Exception as e:
            logger.error(f"Local embedding error: {e}")
            raise ProviderError(f"Local embedding - error generating embedding: {e}")

    async def embed(self, text: str) -> List[float]:
        """
        Generate an embedding for the given text using local sentence-transformers
        """
        return await run_in_threadpool(self._embed_sync, text)
