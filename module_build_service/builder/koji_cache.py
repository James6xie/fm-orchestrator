import dogpile.cache
from KojiModuleBuilder import KojiModuleBuilder
import pylibmc
import koji 

#set up CacheRegion
koji_perm_ids = pylibmc.Client(["127.0.0.1"], binary=True,
				behaviors={"tcp_nodelay": True, 
					   "ketama": True})

region = make_region().configure(
	'koji_perm_ids.pylibmc',
	arguments = {
		'url': ["127.0.0.1"], 
	} 
)

@region.cache_on_arguments()
def generate_perm_id(perm):
    


