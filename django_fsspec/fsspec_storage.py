from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import Storage

from .utils import get_filesystem


def get_random_string(length=6):
    """Generate a random string of fixed length."""
    import random
    import string

    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for i in range(length))


class FsspecStorage(Storage):
    """Django Storage implementation using fsspec

    settings:
    - fsspec
      could be a fsspec filesystem object or a dictionary with fsspec configuration and fs_type for type of filesystem

    example settings with nested filesystem:
    STORAGES = {
        "default": {
            BACKEND: "django_fsspec.storage.FsspecStorage",
            OPTIONS: {
                "storage_config": {
                    "protocol": "transparent",
                    "transparent_fs": {
                        fs: "file",
                        "path": "/path/to/files/transparent",
                    },
                    "underlying_fs": {
                        "fs_type": "nested",
                        "storage_config": {
                        "dir_a": {
                            fs: "s3",
                            "fsspec_config": {
                                "endpoint_url": env.get("S3_TEST_ENDPOINT_URL"),
                                "key": env.get("S3_TEST_ACCESS_KEY"),
                                "secret": env.get("S3_TEST_SECRET_KEY"),
                            },
                            "relative_to_path": env.get("S3_TEST_BUCKET_NAME"),
                        },
                        "dir_b": {
                            fs: "s3",
                            "fsspec_config": {
                                "endpoint_url": env.get("S3_TEST_ENDPOINT_URL"),
                                "key": env.get("S3_TEST_ACCESS_KEY"),
                                "secret": env.get("S3_TEST_SECRET_KEY"),
                            },
                            "relative_to_path": env.get("S3_TEST_BUCKET_NAME2"),
                        },
                        "default": {
                            "fs": "file",
                            "path": "/path/to/default/files",
                        },
                    }
                }
            }
        },
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        }
    }

    from django.core.files.storage import storages

    storage = storages["default"]
    storage.exists("path/to/file")
    storage.open("path/to/file")

    """

    def __init__(self, **settings):
        settings_cp = settings.copy()
        self.location = settings_cp.pop("location", "")
        self.base_url = settings_cp.pop("base_url", None)
        self.file_permissions_mode = settings_cp.pop("file_permissions_mode", None)
        self.directory_permissions_mode = settings_cp.pop("directory_permissions_mode", None)
        self.allow_overwrite = settings_cp.pop("allow_overwrite", True)

        if "storage_config" not in settings_cp:
            raise ImproperlyConfigured("storage_config is required")
        storage_config = settings_cp.pop("storage_config")
        self.filesystem = get_filesystem(**storage_config)

        # extra (not implemented yet)
        # self.allow_delete = settings.get('allow_delete', False)
        # self.allow_write = settings.get('allow_write', False)

        if settings_cp:
            raise ImproperlyConfigured(f"Unknown setting(s): {settings_cp.keys()}")

    def delete(self, name):
        return self.filesystem.rm(name)

    def exists(self, name):
        return self.filesystem.exists(name)

    def listdir(self, path):
        return self.filesystem.ls(path, detail=True)
        details = self.filesystem.ls(path, detail=True)
        files = []
        dirs = []
        for i, item in enumerate(details):
            if i == 0 and name.endswith("/"):
                continue
            if item["type"] == "directory":
                dirs.append(os.path.basename(item.get("name")))
            else:
                files.append(os.path.basename(item.get("name")))
        return dirs, files

    def ls(self, path):
        """Extra: List a directory with details"""
        return self.filesystem.ls(path, detail=True)

    def _open(self, name, mode="rb"):
        return self.filesystem.open(name, mode)

    def path(self, name):
        return name

    def _save(self, name, content, max_length=None):
        if self.allow_overwrite and self.exists(name):
            self.delete(name)
        with self.filesystem.open(name, "wb") as f:
            f.write(content.read())
        return name

    def size(self, name):
        return self.filesystem.size(name)

    def url(self, name):
        return self.base_url + name

    def get_accessed_time(self, name):
        raise NotImplementedError

    def get_alternative_name(self, file_root, file_ext):
        # add underscore and random 6 character string to name (before the file extension, if one exists)
        return "%s_%s%s" % (file_root, get_random_string(6), file_ext)


    def get_created_time(self, name):
        return self.filesystem.created(name)

    def get_modified_time(self, name):
        return self.filesystem.modified(name)

    # optional:
    # def get_accessed_time(self, name):
    # def get_alternative_name(self,file_root, file_ext):
    # def get_created_time(self, name):
    # def get_modified_time(self, name):
    # def get_valid_name(self, name):
    # def generate_filename(self, filename):

    # extra:
    # def url_direct(self, name):
    # def url_signed(self, name, expires=None):
