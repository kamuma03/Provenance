"""Factory + vendor-stub tests (R20/R21/N4)."""

from __future__ import annotations

import pytest
from provenance_contracts import VectorStorePort
from provenance_services.faiss_store import FaissVectorStore
from provenance_services.qdrant_store import QdrantVectorStore
from provenance_services.vector_factory import get_vector_store
from provenance_services.vendor_stubs import OpenSearchVectorStore, WeaviateVectorStore


def test_factory_selects_backend_by_name() -> None:
    assert isinstance(get_vector_store("faiss"), FaissVectorStore)
    assert isinstance(get_vector_store("qdrant"), QdrantVectorStore)
    assert isinstance(get_vector_store("opensearch"), OpenSearchVectorStore)


def test_factory_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError):
        get_vector_store("redis-but-not-a-vector-db")


def test_stubs_satisfy_port_but_raise() -> None:
    for stub in (OpenSearchVectorStore(), WeaviateVectorStore()):
        assert isinstance(stub, VectorStorePort)  # structural conformance (R21)


@pytest.mark.asyncio
async def test_stub_methods_raise_not_implemented() -> None:
    with pytest.raises(NotImplementedError):
        await OpenSearchVectorStore().query("kb", [0.1], 5)
