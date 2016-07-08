#!/usr/bin/env python3
""" A little script to test buildroot creation. """

from rida.builder import KojiModuleBuild, Builder
from rida.config import Config


cfg = Config()
cfg.koji_profile = "koji"
cfg.koji_config = "/etc/rida/koji.conf"
cfg.koji_arches = ["x86_64", "i686"]

#mb = KojiModuleBuild(module="testmodule-1.0", config=cfg) # or By using Builder
mb = Builder(module="testmodule-1.0", backend="koji", config=cfg)

resume = True

if not resume:
    mb.buildroot_prep()
    mb.buildroot_add_dependency(["f24"])
    mb.buildroot_ready()
    task_id = mb.build(artifact_name="fedora-release", source="git://pkgs.fedoraproject.org/rpms/fedora-release?#b1d65f349dca2f597b278a4aad9e41fb0aa96fc9")
    mb.buildroot_add_artifacts(["fedora-release-24-2", ]) # just example with disttag macro
    mb.buildroot_ready(artifact="fedora-release-24-2")
else:
    mb.buildroot_resume()

task_id = mb.build(artifact_name="fedora-release", source="git://pkgs.fedoraproject.org/rpms/fedora-release?#b1d65f349dca2f597b278a4aad9e41fb0aa96fc9")
