import pkg_resources

from module_build_service import conf
from module_build_service.builder.base import GenericBuilder

__all__ = [
    GenericBuilder
]

for entrypoint in pkg_resources.iter_entry_points('mbs.builder_backends'):
    # Only import the copr builder if it is configured since we don't want to include the copr
    # module as a dependency for all installations
    if entrypoint.name != "copr" or conf.system == 'copr':
        GenericBuilder.register_backend_class(entrypoint.load())
