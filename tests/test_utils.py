import unittest
from pathlib import Path

import fsspec
import s3fs
from fsspec.implementations.dirfs import DirFileSystem
from fsspec.implementations.memory import MemoryFileSystem

from django_fsspec.utils import build_virtual_hosted_url
from django_fsspec.utils import get_filesystem
from django_fsspec.utils import unwrap_s3_target

tmp_test_path = Path(Path(__file__).parent, "tmp", "test_media")


def _fake_s3fs():
    """A S3FileSystem that never hits the network — path-parsing is pure string logic."""
    return s3fs.S3FileSystem(
        key="x",
        secret="y",
        endpoint_url="https://example.com",
        skip_instance_cache=True,
    )


class TestGetFilesystem(unittest.TestCase):
    def test_with_fs_as_param(self):
        fs = fsspec.filesystem("file")
        self.assertEqual(("file", "local"), fs.protocol)
        fs_out = get_filesystem(fs)
        self.assertEqual(fs_out, fs)

    def test_with_fs_type_and_config(self):
        fs_out = get_filesystem(protocol="local", auto_mkdir=True)
        self.assertEqual(("file", "local"), fs_out.protocol)

    def test_with_relative_path(self):
        fs_out = get_filesystem(
            protocol="local",
            auto_mkdir=True,
            relative_to_path=tmp_test_path,
        )
        self.assertEqual("dir", fs_out.protocol)


class TestUnwrapS3Target(unittest.TestCase):
    """Offline (no network) coverage for unwrap_s3_target's bucket/key split."""

    def test_bare_bucket(self):
        s3 = _fake_s3fs()
        dfs = DirFileSystem(fs=s3, path="my-bucket")
        fs, bucket, key = unwrap_s3_target(dfs, "foo/bar.jpg")
        self.assertIs(fs, s3)
        self.assertEqual(bucket, "my-bucket")
        self.assertEqual(key, "foo/bar.jpg")

    def test_bucket_with_key_prefix(self):
        """Regression test: relative_to_path combining bucket + extra prefix
        segments (e.g. 'tapp-tijhuis-media/media/media') must not leak the
        whole string into `bucket`."""
        s3 = _fake_s3fs()
        dfs = DirFileSystem(fs=s3, path="tapp-tijhuis-media/media/media")
        fs, bucket, key = unwrap_s3_target(dfs, "2223/photos/xxx.jpg")
        self.assertIs(fs, s3)
        self.assertEqual(bucket, "tapp-tijhuis-media")
        self.assertEqual(key, "media/media/2223/photos/xxx.jpg")

    def test_bare_s3_filesystem(self):
        s3 = _fake_s3fs()
        fs, bucket, key = unwrap_s3_target(s3, "my-bucket/foo/bar.jpg")
        self.assertIs(fs, s3)
        self.assertEqual(bucket, "my-bucket")
        self.assertEqual(key, "foo/bar.jpg")

    def test_non_s3_backend_raises(self):
        dfs = DirFileSystem(fs=MemoryFileSystem(), path="/root")
        with self.assertRaises(NotImplementedError):
            unwrap_s3_target(dfs, "foo/bar.jpg")


class TestBuildVirtualHostedUrl(unittest.TestCase):
    def test_bucket_with_key_prefix_produces_well_formed_url(self):
        # Regression test companion to test_bucket_with_key_prefix above:
        # once bucket/key are split correctly, the resulting URL must not
        # contain '/' before the endpoint host.
        s3 = _fake_s3fs()
        url = build_virtual_hosted_url(s3, "tapp-tijhuis-media", "media/media/2223/photos/xxx.jpg")
        self.assertEqual(url, "https://tapp-tijhuis-media.example.com/media/media/2223/photos/xxx.jpg")
        self.assertNotIn("/", url.split("://", 1)[1].split("/", 1)[0])
