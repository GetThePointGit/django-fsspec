import shutil
import unittest
from pathlib import Path

import fsspec

from django_fsspec.transparent_fs import TransparentFileSystem

test_data_dir = Path(Path(__file__).parent, "tmp")
tmp_get_dir = Path(test_data_dir, "..", "tmp_get").resolve()

root_base_fs = Path(test_data_dir, "root_base_fs")
root_transparent_fs = Path(test_data_dir, "root_transparent_fs")


class TestTransparentFS(unittest.TestCase):
    def setUp(self):
        # Ensure the test directories exist so DirFileSystem accepts them.
        root_base_fs.mkdir(parents=True, exist_ok=True)
        root_transparent_fs.mkdir(parents=True, exist_ok=True)
        self.fs = TransparentFileSystem(
            base_fs={
                "protocol": "file",
                "auto_mkdir": True,
                "relative_to_path": root_base_fs,
            },
            transparent_fs=fsspec.filesystem(
                protocol="dir",
                target_protocol="file",
                target_options={"auto_mkdir": True},
                path=root_transparent_fs,
            ),
        )

    def tearDown(self):
        shutil.rmtree(test_data_dir, ignore_errors=True)
        shutil.rmtree(tmp_get_dir, ignore_errors=True)

    def test_get_filesystem(self):
        base_fs = self.fs.base_fs
        self.assertEqual("dir", base_fs.protocol)

        transparent_fs = self.fs.transparent_fs
        self.assertEqual("dir", transparent_fs.protocol)

    def test_lexists_does_not_crash(self):
        """Regression: lexists() previously called `self._get_filesystem(path)`,
        which is a NestedFileSystem method that does not exist on
        TransparentFileSystem. That copy-paste bug crashed on AttributeError
        the moment lexists() was called.
        """
        # For a non-existing path: must return False, not crash.
        self.assertFalse(self.fs.lexists("does/not/exist.txt"))

        # Write a file and verify that lexists() returns True.
        with self.fs.open("present.txt", "w") as f:
            f.write("hi")
        self.assertTrue(self.fs.lexists("present.txt"))

    # --- ls -------------------------------------------------------------------

    def _seed(self):
        """Plant a file in each layer; return their bytes for assertions."""
        Path(root_base_fs, "b.txt").write_bytes(b"base")
        Path(root_transparent_fs, "t.txt").write_bytes(b"trans")
        return b"base", b"trans"

    def test_ls_detail_true_merges_both_layers(self):
        self._seed()
        names = sorted(e["name"] for e in self.fs.ls("", detail=True))
        self.assertEqual(names, ["b.txt", "t.txt"])
        for entry in self.fs.ls("", detail=True):
            self.assertEqual(entry["type"], "file")

    def test_ls_detail_false_returns_strings(self):
        self._seed()
        result = sorted(self.fs.ls("", detail=False))
        self.assertEqual(result, ["b.txt", "t.txt"])

    def test_ls_overlay_overrides_base(self):
        Path(root_base_fs, "shared.txt").write_bytes(b"base-version")
        Path(root_transparent_fs, "shared.txt").write_bytes(b"overlay-version")
        result = sorted(self.fs.ls("", detail=False))
        self.assertEqual(result, ["shared.txt"])
        self.assertEqual(self.fs.cat_file("shared.txt"), b"overlay-version")

    def test_ls_hides_deleted_tombstones(self):
        Path(root_base_fs, "gone.txt").write_bytes(b"x")
        Path(root_transparent_fs, "gone.txt.deleted").touch()
        names = list(self.fs.ls("", detail=False))
        self.assertEqual(names, [])

    def test_ls_does_not_emit_marker_files(self):
        Path(root_base_fs, "vanished").write_bytes(b"")
        Path(root_transparent_fs, "vanished.deleted").touch()
        Path(root_transparent_fs, "redone.replaced").mkdir()
        names = sorted(self.fs.ls("", detail=False))
        # Tombstones for "vanished" hide it; "redone" was replaced but has no
        # actual content yet so neither name should appear in the listing.
        self.assertEqual(names, [])

    # --- walk / find ----------------------------------------------------------
    #
    # Regression tests for issue #10: the old hand-rolled walk() override
    # ignored the ``path`` argument, and its tombstone handling replaced the
    # accumulator dict with a list, after which iteration crashed with
    # "'list' object has no attribute 'items'". The override is gone; walk()
    # now comes from AbstractFileSystem and is built on the (correct) ls().

    def _seed_tree(self):
        """Nested content in both layers sharing the directory ``docs/``."""
        Path(root_base_fs, "docs").mkdir()
        Path(root_base_fs, "docs", "base.txt").write_bytes(b"b")
        Path(root_base_fs, "top-base.txt").write_bytes(b"tb")
        Path(root_transparent_fs, "docs").mkdir()
        Path(root_transparent_fs, "docs", "overlay.txt").write_bytes(b"o")
        Path(root_transparent_fs, "top-overlay.txt").write_bytes(b"to")

    def test_walk_merges_both_layers(self):
        self._seed_tree()
        seen = {p: (sorted(dirs), sorted(files)) for p, dirs, files in self.fs.walk("")}
        self.assertEqual(seen[""], (["docs"], ["top-base.txt", "top-overlay.txt"]))
        self.assertEqual(seen["docs"], ([], ["base.txt", "overlay.txt"]))

    def test_walk_respects_path_argument(self):
        """The old override always walked from the root, whatever ``path``
        was passed."""
        self._seed_tree()
        seen = dict.fromkeys(p for p, _, _ in self.fs.walk("docs"))
        self.assertEqual(list(seen), ["docs"])

    def test_walk_with_tombstone_does_not_crash_and_hides_entry(self):
        self._seed_tree()
        self.fs.rm("docs/base.txt")  # tombstone on the overlay
        seen = {p: sorted(files) for p, _, files in self.fs.walk("")}
        self.assertEqual(seen["docs"], ["overlay.txt"])

    def test_walk_detail_true_yields_entry_dicts(self):
        """walk(detail=True) must yield ({name: info}, {name: info}) dicts;
        the old override mangled these into plain name lists."""
        self._seed_tree()
        for _path, dirs, files in self.fs.walk("", detail=True):
            self.assertIsInstance(dirs, dict)
            self.assertIsInstance(files, dict)
            for info in (*dirs.values(), *files.values()):
                self.assertIn("type", info)

    def test_find_lists_files_from_both_layers(self):
        """find() is built on walk(); this is the file_check.populate_source
        scenario that crashed in production."""
        self._seed_tree()
        found = sorted(self.fs.find(""))
        self.assertEqual(
            found,
            ["docs/base.txt", "docs/overlay.txt", "top-base.txt", "top-overlay.txt"],
        )
        detailed = self.fs.find("", detail=True)
        self.assertIsInstance(detailed, dict)
        self.assertEqual(sorted(detailed), found)

    # --- rm -------------------------------------------------------------------

    def test_rm_overlay_only_file(self):
        Path(root_transparent_fs, "x.txt").write_bytes(b"hi")
        self.fs.rm("x.txt")
        self.assertFalse(self.fs.exists("x.txt"))
        self.assertFalse(Path(root_transparent_fs, "x.txt").exists())

    def test_rm_base_only_file_leaves_tombstone(self):
        Path(root_base_fs, "x.txt").write_bytes(b"hi")
        self.fs.rm("x.txt")
        self.assertFalse(self.fs.exists("x.txt"))
        # Base file is left untouched (read-only contract); tombstone records
        # the deletion in the overlay.
        self.assertTrue(Path(root_base_fs, "x.txt").exists())
        self.assertTrue(Path(root_transparent_fs, "x.txt.deleted").exists())

    def test_rm_both_layers_records_tombstone(self):
        Path(root_base_fs, "x.txt").write_bytes(b"base")
        Path(root_transparent_fs, "x.txt").write_bytes(b"overlay")
        self.fs.rm("x.txt")
        self.assertFalse(self.fs.exists("x.txt"))
        self.assertFalse(Path(root_transparent_fs, "x.txt").exists())
        self.assertTrue(Path(root_transparent_fs, "x.txt.deleted").exists())

    def test_rm_missing_raises_filenotfound(self):
        with self.assertRaises(FileNotFoundError):
            self.fs.rm("does/not/exist.txt")

    def test_rm_non_empty_dir_without_recursive_raises(self):
        Path(root_base_fs, "subdir").mkdir()
        Path(root_base_fs, "subdir", "child.txt").write_bytes(b"x")
        with self.assertRaises(OSError):
            self.fs.rm("subdir")

    # --- write/read paths -----------------------------------------------------

    def test_open_write_lands_on_overlay_only(self):
        with self.fs.open("a.txt", "w") as f:
            f.write("hi")
        self.assertTrue(Path(root_transparent_fs, "a.txt").exists())
        self.assertFalse(Path(root_base_fs, "a.txt").exists())
        self.assertEqual(self.fs.cat_file("a.txt"), b"hi")

    def test_read_falls_through_to_base(self):
        Path(root_base_fs, "b.txt").write_bytes(b"from-base")
        self.assertEqual(self.fs.cat_file("b.txt"), b"from-base")

    def test_size_uses_active_layer(self):
        Path(root_base_fs, "b.txt").write_bytes(b"base")
        Path(root_transparent_fs, "b.txt").write_bytes(b"overlay-longer")
        self.assertEqual(self.fs.size("b.txt"), len(b"overlay-longer"))

    # --- contract edge cases --------------------------------------------------

    def test_ls_missing_path_raises(self):
        """fsspec contract: `ls` raises FileNotFoundError when neither
        layer has the path. Previously the missing-path errors were
        silently swallowed and an empty list was returned."""
        with self.assertRaises(FileNotFoundError):
            self.fs.ls("does/not/exist")

    def test_ls_succeeds_when_only_one_layer_has_the_path(self):
        Path(root_base_fs, "subdir").mkdir()
        Path(root_base_fs, "subdir", "b.txt").write_bytes(b"x")
        # Overlay does not have `subdir/`; ls must still return base content.
        result = sorted(self.fs.ls("subdir", detail=False))
        self.assertEqual(result, ["subdir/b.txt"])

    def test_rm_directory_when_overlay_holds_only_tombstones(self):
        """A directory whose entire content has been hidden via overlay
        tombstones should remove cleanly: the overlay-side bookkeeping
        files must be cleared and the directory must vanish from the
        merged view."""
        Path(root_base_fs, "ghost").mkdir()
        Path(root_base_fs, "ghost", "g1.txt").write_bytes(b"g1")
        Path(root_base_fs, "ghost", "g2.txt").write_bytes(b"g2")

        # Hide both files via overlay tombstones.
        self.fs.rm("ghost/g1.txt")
        self.fs.rm("ghost/g2.txt")
        # Merged view of ghost/ is empty.
        self.assertEqual(list(self.fs.ls("ghost", detail=False)), [])

        # Now rm the directory. Should not raise on the leftover overlay
        # bookkeeping (g1.txt.deleted, g2.txt.deleted).
        self.fs.rm("ghost")
        self.assertFalse(self.fs.exists("ghost"))
        # Overlay's stale tombstones are gone…
        self.assertFalse(Path(root_transparent_fs, "ghost").exists())
        # …but a new tombstone for the directory itself is recorded so the
        # base directory does not reappear in the merged view.
        self.assertTrue(Path(root_transparent_fs, "ghost.deleted").exists())


class TestResolveS3TargetWriteAware(unittest.TestCase):
    """`resolve_s3_target(for_write=True)` — offline (S3FileSystem is lazy,
    instantiation does not connect).

    Writes must resolve against the writable overlay so presigned PUT URLs
    target the bucket the overlay actually writes to. Read resolution is
    covered by ``TestResolveS3TargetReadLayerAware`` below.
    """

    def _s3_config(self, relative_to_path, tag):
        # Distinct config_kwargs per fs to sidestep the s3fs instance cache.
        return {
            "protocol": "s3",
            "key": "test-key",
            "secret": "test-secret",
            "endpoint_url": "http://127.0.0.1:9",
            "config_kwargs": {"user_agent": tag},
            "relative_to_path": relative_to_path,
        }

    def _overlay(self):
        return TransparentFileSystem(
            base_fs=self._s3_config("prod-bucket", "base"),
            transparent_fs=self._s3_config("dev-bucket/dev/upload", "overlay"),
        )

    def test_for_write_resolves_overlay(self):
        _s3_fs, bucket, key = self._overlay().resolve_s3_target("foo.bin", for_write=True)
        self.assertEqual("dev-bucket", bucket)
        self.assertEqual("dev/upload/foo.bin", key)

    def test_for_write_local_overlay_raises(self):
        """A local overlay cannot issue presigned URLs — must raise, so the
        caller can map it to an HTTP 501."""
        root_base_fs.mkdir(parents=True, exist_ok=True)
        root_transparent_fs.mkdir(parents=True, exist_ok=True)
        fs = TransparentFileSystem(
            base_fs=self._s3_config("prod-bucket", "base2"),
            transparent_fs={
                "protocol": "file",
                "auto_mkdir": True,
                "relative_to_path": root_transparent_fs,
            },
        )
        with self.assertRaises(NotImplementedError):
            fs.resolve_s3_target("foo.bin", for_write=True)


class TestResolveS3TargetReadLayerAware(unittest.TestCase):
    """Read resolution must pick the layer that actually holds the file.

    A fresh overlay-only upload (dev: everything written lands on the
    overlay bucket) signed against the base bucket would 404 on the
    presigned GET. Offline — the layers' ``exists`` probes are stubbed;
    the S3FileSystem objects stay lazy and never connect.
    """

    def _s3_config(self, relative_to_path, tag):
        # Distinct config_kwargs per fs to sidestep the s3fs instance cache.
        return {
            "protocol": "s3",
            "key": "test-key",
            "secret": "test-secret",
            "endpoint_url": "http://127.0.0.1:9",
            "config_kwargs": {"user_agent": tag},
            "relative_to_path": relative_to_path,
        }

    def _overlay(self, overlay_has=(), base_has=()):
        fs = TransparentFileSystem(
            base_fs=self._s3_config("prod-bucket", "rbase"),
            transparent_fs=self._s3_config("dev-bucket/dev/upload", "roverlay"),
        )
        fs.transparent_fs.exists = lambda p: p in overlay_has
        fs.base_fs.exists = lambda p: p in base_has
        return fs

    def test_read_overlay_only_file_resolves_overlay(self):
        fs = self._overlay(overlay_has={"foo.bin"})
        _s3_fs, bucket, key = fs.resolve_s3_target("foo.bin")
        self.assertEqual("dev-bucket", bucket)
        self.assertEqual("dev/upload/foo.bin", key)

    def test_read_base_file_resolves_base(self):
        fs = self._overlay(base_has={"foo.bin"})
        _s3_fs, bucket, key = fs.resolve_s3_target("foo.bin")
        self.assertEqual("prod-bucket", bucket)
        self.assertEqual("foo.bin", key)

    def test_read_missing_file_falls_back_to_base(self):
        fs = self._overlay()
        _s3_fs, bucket, key = fs.resolve_s3_target("foo.bin")
        self.assertEqual("prod-bucket", bucket)
        self.assertEqual("foo.bin", key)

    def test_tombstoned_file_resolves_base(self):
        """A ``.deleted`` tombstone hides the base file; resolution then
        falls back to base. Callers check ``exists`` on the merged view
        first, so this path is unreachable for real downloads."""
        fs = self._overlay(overlay_has={"foo.bin.deleted"}, base_has={"foo.bin"})
        _s3_fs, bucket, key = fs.resolve_s3_target("foo.bin")
        self.assertEqual("prod-bucket", bucket)

    def test_for_write_needs_no_layer_probe(self):
        """Write resolution is static (always the overlay) and must not
        spend network calls on existence probes."""
        fs = self._overlay()

        def _boom(_p):
            raise AssertionError("write resolve must not probe layer existence")

        fs.transparent_fs.exists = _boom
        fs.base_fs.exists = _boom
        _s3_fs, bucket, key = fs.resolve_s3_target("foo.bin", for_write=True)
        self.assertEqual("dev-bucket", bucket)
        self.assertEqual("dev/upload/foo.bin", key)
