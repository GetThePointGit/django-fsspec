CHANGELOG
=========

0.1.6b1 (unreleased)
--------------------

Write-aware ``resolve_s3_target`` so presigned PUT URLs work on overlay
(transparent) configurations.

- New optional keyword ``for_write=False`` on
  ``NestedFileSystem.resolve_s3_target``,
  ``TransparentFileSystem.resolve_s3_target`` and
  ``FsspecStorage._resolve_s3_target``.
- ``TransparentFileSystem.resolve_s3_target(for_write=True)`` resolves
  against the writable ``transparent_fs`` overlay instead of the
  read-only ``base_fs`` — a presigned PUT signed against ``base_fs``
  would bypass the overlay's read-only contract. Reads keep resolving
  against ``base_fs`` (unchanged). A local (non-S3) overlay raises
  ``NotImplementedError`` so callers can map it to an HTTP 501.
- ``NestedFileSystem.resolve_s3_target`` now delegates to a matched
  sub-filesystem's own ``resolve_s3_target`` when it has one (e.g. a
  transparent overlay), instead of blindly unwrapping — previously an
  overlay sub-fs raised ``NotImplementedError`` even for reads.
- ``FsspecStorage.url_signed(method='PUT')`` resolves with
  ``for_write=True``; GET signing is unchanged.

0.1.3 (unreleased)
------------------

Cross-filesystem ``cp_file`` / ``mv`` now verify the copy before reporting
success.

- ``NestedFileSystem.cp_file`` (cross-fs branch) compares the destination
  size to the local tempfile size after upload. On mismatch the destination
  is removed and ``IOError`` is raised; the source is untouched. Same-fs
  copies are delegated to the sub-fs and are unchanged.
- New keyword-only argument ``verify_checksum=False`` on ``cp_file`` and
  ``mv``. When set to ``True`` it adds a portable-string-checksum compare
  on top of the size check, with graceful skip for backends that do not
  return string checksums (local FS returns ``int(size+mtime)``) or that
  raise ``NotImplementedError``. Files at or above ``_NON_MULTIPART_LIMIT``
  (5 MiB) skip the checksum compare because S3 multipart ETags are not
  portable across backends.
- ``NestedFileSystem.mv`` (cross-fs branch) now confirms the destination
  exists after the copy before removing the source. If a backend silently
  produced no destination the source is preserved and ``IOError`` is
  raised — previous behavior was to ``rm`` the source unconditionally,
  which could cause data loss.
- **Drop Python 3.11 support.** Minimum is now Python 3.12. The test matrix
  (CI, ``tox``, ``pixi``) and ``requires-python`` are updated accordingly.
- Fixed ``unwrap_s3_target`` (used by ``resolve_s3_target``,
  ``FsspecStorage.url_direct()`` and ``FsspecStorage.url_signed()``)
  mis-resolving the S3 bucket when a ``DirFileSystem``'s ``relative_to_path``
  combines a bucket name with extra key-prefix segments (e.g.
  ``"my-bucket/uploads/2026"``). Previously the *entire* prefixed string was
  treated as the bucket, producing an invalid bucket name — this broke
  ``url_direct()`` (malformed virtual-hosted URL) and
  ``url_signed(method="PUT")`` (botocore rejected the multi-segment
  ``Bucket`` param). Bucket/key are now split via ``s3fs``'s own
  ``S3FileSystem.split_path()``, and the path fed to it is built via
  ``DirFileSystem._join()`` so it matches exactly what real I/O
  (``open``/``get``/``put``) resolves to. Normal storage reads/writes were
  never affected.

0.1.2 (unreleased)
------------------

Behavior alignment and error-message polish on top of ``0.1.1``.

- ``FsspecStorage.delete(name)`` is now idempotent on a missing file —
  matches Django's ``FileSystemStorage.delete`` contract. The fsspec
  layer still raises ``FileNotFoundError``; the wrapper swallows it.
  ``allow_delete=False`` continues to raise ``PermissionError`` as
  before.
- ``NestedFileSystem.rm("", recursive=True)`` walks every sub-filesystem
  instead of clearing only the matched / default one. Resolves the
  longstanding ``# todo: if recursive, find other fs`` in
  ``nested_fs.py``.
- ``NestedFileSystem`` operations on an unmatched path (no sub-fs and
  no ``"default"``) now raise ``FileNotFoundError`` with the offending
  path in the message, instead of generic ``ValueError``s. Affected
  methods: ``rm``, ``mkdir``, ``makedirs``, ``rmdir``, ``put``.
  ``rmdir("")`` keeps a more specific ``ValueError`` because removing
  the conceptual root is a configuration mistake, not a missing file.
- **Drop Django 5.0 support.** Minimum is now Django 5.1. Django 5.0 has
  been end-of-life since April 2025, and ``FsspecStorage`` relies on the
  ``is_name_available`` / ``allow_overwrite`` ``Storage`` API that was
  introduced in Django 5.1 to enforce ``on_collision`` policies.


0.1.1rc1 (2026-04-28)
---------------------

Release-candidate cut after a pre-RC audit.

Configuration and validation
- Per-protocol validation in ``get_filesystem``: ``protocol="s3"`` requires
  ``relative_to_path`` (the bucket and optional key prefix); ``"nested"``
  requires ``path_storage_configs``; ``"transparent"`` requires both
  ``transparent_fs`` and ``base_fs``. Misconfiguration raises
  ``ImproperlyConfigured`` with a message that names the missing key.
- ``OPTIONS["location"]`` is bridged into ``storage_config["relative_to_path"]``
  for ``protocol="file"``/``"local"`` and refused for any other protocol
  (semantics differ per backend; we no longer guess silently). Setting
  both at once is an ``ImproperlyConfigured``.
- ``file_permissions_mode`` and ``directory_permissions_mode`` emit a
  ``DeprecationWarning`` (removed in 0.2.0) — they are not honored by any
  fsspec backend.

Permissions and collision policy
- New ``permissions`` dict (``allow_read`` / ``allow_write`` /
  ``allow_delete``, all default ``True``). Denied actions raise
  ``PermissionError``. Available at top-level ``OPTIONS`` and per sub-fs
  inside ``path_storage_configs``; the effective set is pre-computed
  with most-restrictive-wins semantics.
- New ``on_collision`` setting (``"overwrite"`` / ``"rename"`` /
  ``"raise"``, default ``"overwrite"``) replaces the deprecated
  ``allow_overwrite``. ``allow_overwrite`` keeps working with a
  ``DeprecationWarning`` and is mapped onto ``on_collision`` (removed in
  0.2.0). Setting both at once raises.
- ``url_signed(method="PUT")`` honors ``allow_write`` and refuses upfront
  when ``on_collision`` would block the implicit overwrite (presigned URLs
  are opaque after issuance).
- ``NestedFileSystem`` accepts ``permissions`` and ``on_collision`` on
  every sub-fs entry. The previously dead ``nested_permissions`` key is
  removed.

TransparentFileSystem fixes (critical)
- ``ls`` worked in neither branch (``detail=True`` crashed on
  ``dict.endswith``; ``detail=False`` crashed on ``string["name"]``).
  Rewritten to read both layers in detail-first form, apply
  tombstone/replacement logic uniformly, and honor fsspec's
  ``FileNotFoundError`` contract when neither layer has the path.
- ``rm(path)`` on a base-only file used to crash via a buggy empty-check.
  Files now remove cleanly; directories whose merged view is empty but
  whose overlay still holds tombstone bookkeeping are now removed
  recursively on the overlay.
- ``mkdirs`` calls standardized to ``makedirs(path, exist_ok=...)``
  throughout.

Documentation and tooling
- README expanded with a Configuration reference (per-protocol option
  tables, ``relative_to_path`` semantics, permissions and on_collision
  guide), a Limitations section (``storage.filesystem`` bypass, presigned
  PUT race window, ``delete()`` divergence from ``FileSystemStorage``,
  recursive ``rm`` on nested root), and a migration table for
  ``allow_overwrite``.
- Test matrix expanded to Django 5.2 (LTS) and Django 6.0; dependency
  pin tightened to ``Django>=5.0,<7``. CI matrix switched to an explicit
  ``include`` list matching Django's own python × django support grid.
- Test settings bootstrap moved from ``tests/test_fsspec_storage.py`` to
  ``tests/conftest.py`` (guarded by ``settings.configured``) so future
  Django-aware test modules can co-exist.
- Test count grew from ~20 to 80 unit tests (plus the unchanged S3
  integration suite).

0.1.0b1 (2026-04-20)
--------------------

First beta release. First PyPI release under
``bastiaan-roos/django-fsspec``.

- Presigned S3 URLs: ``FsspecStorage.url_signed(name, expires, method,
  response_headers)`` for GET/PUT, plus ``url_direct(name)`` for
  public-read buckets. SigV4 enforced for interop with DigitalOcean
  Spaces and other S3-compatible providers.
- ``NestedFileSystem.resolve_s3_target(path)`` unwraps a nested path to
  ``(S3FileSystem, bucket, key)``. ``TransparentFileSystem`` delegates
  signing to its ``base_fs``.
- Optional integrity check: ``FsspecStorage(verify_checksum=True)``
  compares ``content.checksum`` against the stored checksum after upload
  and removes the object on mismatch.
- ``s3fs`` and ``boto3`` moved to an optional ``[s3]`` extra
  (``pip install django-fsspec[s3]``).
- Bug fixes landed on ``FsspecStorage`` (``path``, ``url``, ``listdir``,
  streaming ``_save``, parent ``makedirs``, ``allow_overwrite``),
  ``NestedFileSystem`` (``_get_filesystem`` without default, ``cp_file``/
  ``mv`` tuple unpacking, ``walk`` / ``ls`` on sub-fs), and
  ``TransparentFileSystem.lexists``.
- Test suite runs against Python 3.11–3.13 × Django 5.0/5.1, covers the
  presigned-URL and resolver code paths against a real S3 backend, and
  switched to ``python-dotenv`` for env loading (no credentials in
  test code).
- Dev classifier bumped from Pre-Alpha to Beta.
