# -*- coding: utf-8 -*-
#
# Copyright © 2018  Red Hat, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# Written by Jan Kaluža <jkaluza@redhat.com>
#            Igor Gnatenko <ignatenko@redhat.com>

import itertools
import solv
from module_build_service import log


class MMDResolver(object):
    """
    Resolves dependencies between Module metadata objects.
    """

    def __init__(self):
        self.pool = solv.Pool()
        self.pool.setarch("x86_64")
        self.build_repo = self.pool.add_repo("build")
        self.available_repo = self.pool.add_repo("available")

    def add_modules(self, mmd):
        n, s, v, c = mmd.get_name(), mmd.get_stream(), mmd.get_version(), mmd.get_context()

        pool = self.pool

        solvables = []
        if c is not None:
            # Built module
            deps = mmd.get_dependencies()
            if len(deps) > 1:
                raise ValueError(
                    "The built module contains different runtime dependencies: %s" % mmd.dumps())

            # $n:$s:$v:$c-$v.$a
            solvable = self.available_repo.add_solvable()
            solvable.name = "%s:%s:%d:%s" % (n, s, v, c)
            solvable.evr = str(v)
            # TODO: replace with real arch
            solvable.arch = "x86_64"

            # Prv: module($n)
            solvable.add_deparray(solv.SOLVABLE_PROVIDES,
                                  pool.Dep("module(%s)" % n))
            # Prv: module($n:$s) = $v
            solvable.add_deparray(solv.SOLVABLE_PROVIDES,
                                  pool.Dep("module(%s:%s)" % (n, s)).Rel(
                                      solv.REL_EQ, pool.Dep(str(v))))

            if deps:
                # Req: (module($on1:$os1) OR module($on2:$os2) OR …)
                for name, streams in deps[0].get_requires().items():
                    requires = None
                    for stream in streams.get():
                        require = pool.Dep("module(%s:%s)" % (name, stream))
                        if requires is not None:
                            requires = requires.Rel(solv.REL_OR, require)
                        else:
                            requires = require
                    solvable.add_deparray(solv.SOLVABLE_REQUIRES, requires)

            # Con: module($n)
            solvable.add_deparray(solv.SOLVABLE_CONFLICTS, pool.Dep("module(%s)" % n))

            solvables.append(solvable)
        else:
            # Input module
            # Context means two things:
            # * Unique identifier
            # * Offset for the dependency which was used
            for c, deps in enumerate(mmd.get_dependencies()):
                # $n:$s:$c-$v.src
                solvable = self.build_repo.add_solvable()
                solvable.name = "%s:%s:%d:%d" % (n, s, v, c)
                solvable.evr = str(v)
                solvable.arch = "src"

                # Req: (module($on1:$os1) OR module($on2:$os2) OR …)
                for name, streams in deps.get_buildrequires().items():
                    requires = None
                    for stream in streams.get():
                        require = pool.Dep("module(%s:%s)" % (name, stream))
                        if requires:
                            requires = requires.Rel(solv.REL_OR, require)
                        else:
                            requires = require
                    solvable.add_deparray(solv.SOLVABLE_REQUIRES, requires)

                solvables.append(solvable)

        return solvables

    def solve(self, mmd):
        """
        Solves dependencies of module defined by `mmd` object. Returns set
        containing frozensets with all the possible combinations which
        satisfied dependencies.

        :return: set of frozensets of n:s:v:c of modules which satisfied the
            dependency solving.
        """
        solvables = self.add_modules(mmd)
        if not solvables:
            raise ValueError("No module(s) found for resolving")
        self.pool.createwhatprovides()

        solver = self.pool.Solver()
        alternatives = {}
        for src in solvables:
            job = self.pool.Job(solv.Job.SOLVER_INSTALL | solv.Job.SOLVER_SOLVABLE, src.id)
            requires = src.lookup_deparray(solv.SOLVABLE_REQUIRES)
            alts = alternatives[src] = {}
            # XXX: can be optimized by favoring just by name, but requires additional handling
            #      of context due to name which would contain just N:S.
            for opt in itertools.product(*[self.pool.whatprovides(dep) for dep in requires]):
                log.debug("Testing %s with combination: %s", src, opt)
                key = tuple(":".join(s.name.split(":", 2)[:2]) for s in opt)
                if key in alts:
                    log.debug("%s was already resolved, skipping", key)
                    continue
                jobs = [self.pool.Job(solv.Job.SOLVER_FAVOR | solv.Job.SOLVER_SOLVABLE, s.id)
                        for s in opt] + [job]
                log.debug("Jobs:")
                for j in jobs:
                    log.debug("  - %s", j)
                problems = solver.solve(jobs)
                if problems:
                    raise RuntimeError("Problems were found during solve(): %s" % ", ".join(
                                       str(p) for p in problems))
                newsolvables = solver.transaction().newsolvables()
                log.debug("Transaction:")
                for s in newsolvables:
                    log.debug("  - %s", s)
                alts[key] = newsolvables

        return set(frozenset("%s:%s" % (s.name, s.arch) for s in t)
                   for trans in alternatives.values() for t in trans.values())
