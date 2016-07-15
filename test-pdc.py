#!/usr/bin/env python3
""" A little script to test pdc interaction. """

from rida.pdc import *
from rida.config import Config


cfg = Config()
cfg.pdc_url = "http://localhost:8000/rest_api/v1"
cfg.pdc_insecure = True
cfg.pdc_develop = True

pdc_session = get_pdc_client_session(cfg)
module = get_module(pdc_session, {'name': 'testmodule', 'version': '4.3.42', 'release': '0'})

if module:
    print ("pdc_data=%s" % str(module))
    print ("deps=[%s]" % ", ".join(get_module_dependencies(pdc_session, module)))
    print ("build_deps=[%s]" % ", ".join(get_module_build_dependencies(pdc_session, module)))
    print ("tag=%s" % get_module_tag(pdc_session, module))
else:
    print ('module was not found')
