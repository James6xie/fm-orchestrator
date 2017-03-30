from base import GenericBuilder
from KojiModuleBuilder import KojiModuleBuilder
from CoprModuleBuilder import CoprModuleBuilder
from MockModuleBuilder import MockModuleBuilder

__all__ = [
    GenericBuilder
]


GenericBuilder.register_backend_class(KojiModuleBuilder)
GenericBuilder.register_backend_class(CoprModuleBuilder)
GenericBuilder.register_backend_class(MockModuleBuilder)
