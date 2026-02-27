import os
import tempfile

import pytest

from remy.memory import embeddings


def test_torch_cache_env_set():
    # module import should have ensured the variable exists
    assert "TORCHINDUCTOR_CACHE_DIR" in os.environ
    # it should not point at /tmp by default
    assert "/tmp" not in os.environ["TORCHINDUCTOR_CACHE_DIR"]


def test_cleanup_tmp_cache(tmp_path, monkeypatch):
    fake_tmp = tmp_path / "fake"
    fake_tmp.mkdir()
    # create some dummy cache dirs
    (fake_tmp / "torchinductor_a").mkdir()
    (fake_tmp / "other").mkdir()

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fake_tmp))
    embeddings._cleanup_tmp_cache()

    # only the non-cache directory should remain
    assert not (fake_tmp / "torchinductor_a").exists()
    assert (fake_tmp / "other").exists()


@pytest.mark.asyncio
async def test_embed_retries_on_disk_full(monkeypatch):
    # simulate a model whose encode raises OSError 28 once
    class FakeArray(list):
        def tolist(self):
            return list(self)

    class FakeModel:
        def __init__(self):
            self.called = 0

        def encode(self, text, normalize_embeddings=True):
            self.called += 1
            if self.called == 1:
                raise OSError(28, "No space left")
            # return something that has .tolist()
            return FakeArray([1.23, 4.56])

    fake = FakeModel()
    monkeypatch.setattr(embeddings, "_model_instance", fake)

    store = embeddings.EmbeddingStore(db=None)  # db not used for embed()
    result = await store.embed("foo")
    assert result == [1.23, 4.56]
    assert fake.called == 2
