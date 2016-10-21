#!/bin/bash

# default's *42* lkocman's *43 as well

for mvr in  testmodule-4.3.43-1 testmodule-4.3.42-1; do
    koji --config /etc/module_build_service/koji.conf remove-target $mvr
    koji --config /etc/module_build_service/koji.conf remove-tag $mvr
    koji --config /etc/module_build_service/koji.conf remove-tag $mvr-build
done
