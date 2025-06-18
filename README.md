# Django fsspec

Django Storage backend for <a href="https://filesystem-spec.readthedocs.io/">fsspec</a>.
With this packages all filesystems supported by fsspec can be used as Django storage backends.

Beside the storage implementation, also to 'composed' ffspec filesystems are added:
- `NestedFileSystem`: with this ffspec filesystem, subdirectories of a storage backend point to different ffspec 
   filesystems.
- `TransparentFileSystem`: with this ffspec filesystem, one fs can overlay another fs. This can be useful for 
  testing purposes, e.g. to use a local filesystem as writeble layer over a read only remote filesystem.

## Installation

```bash
pip install django-fsspec
```

## Usage

Within django, storage backends are defined in the settings.py file.


```python

STORAGES = {
    'default': {
        'BACKEND': 'django_fsspec.storage.FsSpecStorage',
        'OPTIONS': {
            'fs_class': 'fsspec.implementations.local.LocalFileSystem',
            'kwargs': {
                'auto_mkdir': True,
            },
        },
    },
}
```







