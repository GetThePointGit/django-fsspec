"""Opnieuw openen van een bestand via ``FieldFile`` / ``File.open()``.

Django's ``FieldFile.open()`` roept ``self.file.open(mode)`` aan zodra het
bestandsobject al eens is opgehaald. Het object dat ``FsspecStorage._open``
teruggeeft moet dat dus ondersteunen, ook voor backends zonder lokaal pad
(S3, memory): open -> terug naar het begin, gesloten -> opnieuw openen via de
storage.
"""

import uuid

import pytest
from django.core.files.base import ContentFile
from django.core.files.base import File

from django_fsspec import FsspecStorage
from django_fsspec.fsspec_storage import FsspecFile

CONTENT = b"abcdef"


def _memory_storage(tmp_path):
    """Storage op een eigen memory-filesystem (geen lokaal pad, zoals S3)."""
    return FsspecStorage(
        storage_config={"protocol": "dir", "path": f"/reopen-{uuid.uuid4().hex}", "target_protocol": "memory"},
    )


def _local_storage(tmp_path):
    """Storage op een lokale map; ``LocalFileOpener`` heeft ook geen ``open()``."""
    return FsspecStorage(
        storage_config={"protocol": "dir", "path": str(tmp_path), "target_protocol": "local"},
    )


@pytest.fixture(params=[_memory_storage, _local_storage], ids=["memory", "local"])
def storage(request, tmp_path):
    """Storage per backend, met een bestand ``data.bin``."""
    storage = request.param(tmp_path)
    storage.save("data.bin", ContentFile(CONTENT))
    return storage


@pytest.fixture
def local_storage(tmp_path):
    """Lokale storage: ``close()`` sluit daar echt (memory-bestanden blijven open, zoals BytesIO)."""
    storage = _local_storage(tmp_path)
    storage.save("data.bin", ContentFile(CONTENT))
    return storage


def test_open_returns_django_file(storage):
    fh = storage.open("data.bin", "rb")
    assert isinstance(fh, File)
    assert isinstance(fh, FsspecFile)
    assert fh.name == "data.bin"
    assert fh.read() == CONTENT
    fh.close()


def test_open_while_open_rewinds(storage):
    fh = storage.open("data.bin", "rb")
    assert fh.read(3) == CONTENT[:3]
    assert fh.open("rb") is fh
    assert fh.read() == CONTENT
    fh.close()


def test_open_after_close_reopens_via_storage(local_storage):
    fh = local_storage.open("data.bin", "rb")
    fh.read()
    fh.close()
    assert fh.closed
    with fh.open("rb") as again:
        assert again.read() == CONTENT
    assert fh.closed


def test_fieldfile_open_twice(storage):
    """Reproductie van waterworks WATERWORKS-PYTHON-1X: tweede ``FieldFile.open()``."""
    from django.db.models.fields.files import FieldFile
    from test_app.models import FieldTestModel

    field = FieldTestModel._meta.get_field("file")
    field_file = FieldFile(FieldTestModel(), field, "data.bin")
    field_file.storage = storage

    with field_file.open("rb") as first:
        assert first.read() == CONTENT
    with field_file.open("rb") as second:
        assert second.read() == CONTENT


def test_reopen_respects_read_permission(local_storage):
    fh = local_storage.open("data.bin", "rb")
    fh.close()
    local_storage.permissions = {**local_storage.permissions, "allow_read": False}
    with pytest.raises(PermissionError):
        fh.open("rb")


def test_unknown_attributes_fall_through_to_underlying_file(storage):
    fh = storage.open("data.bin", "rb")
    # fsspec-bestanden hebben o.a. ``fs``; wie dat gebruikte, mag niet breken.
    assert fh.fs is fh.file.fs
    fh.close()
