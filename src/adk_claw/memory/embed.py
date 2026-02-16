from __future__ import annotations

from functools import lru_cache

import numpy as np
from google import genai
from google.genai import types


@lru_cache(maxsize=1)
def _get_client() -> genai.Client:
    return genai.Client()


def embed_texts(texts: list[str]) -> list[np.ndarray]:
    """Batch-embed texts using Gemini embedding API.

    Returns a list of float32 numpy arrays (768-dim each).
    """
    client = _get_client()
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=texts,
        config=types.EmbedContentConfig(
            output_dimensionality=768,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(initial_delay=2, attempts=5)
            ),
        ),
    )
    return [np.array(e.values, dtype=np.float32) for e in response.embeddings]


def embed_query(text: str) -> np.ndarray:
    """Embed a single query string."""
    return embed_texts([text])[0]
