import pkg_resources

from base import GenericBuilder

__all__ = [
    GenericBuilder
]

for entrypoint in pkg_resources.iter_entry_points('mbs.builder_backends'):
    GenericBuilder.register_backend_class(entrypoint.load())
