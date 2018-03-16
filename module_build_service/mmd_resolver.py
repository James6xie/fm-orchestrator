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

import enum
import collections
import itertools
import solv
from module_build_service import log


class MMDResolverPolicy(enum.Enum):
    All = "all"      # All possible top-level combinations
    First = "first"  # All possible top-level combinations (filtered by N:S, first picked)


class MMDResolver(object):
    """
    Resolves dependencies between Module metadata objects.
    """

    def __init__(self):
        self.pool = solv.Pool()
        self.pool.setarch("x86_64")
        self.build_repo = self.pool.add_repo("build")
        self.available_repo = self.pool.add_repo("available")

    def _deps2reqs(self, deps):
        pool = self.pool

        rel_or_dep = lambda dep, op, rel: dep.Rel(op, rel) if dep is not None else rel
        stream_dep = lambda n, s: pool.Dep("module(%s:%s)" % (n, s))

        reqs = None
        for deps in deps:
            require = None
            for name, streams in deps.items():
                req_pos = req_neg = None
                for stream in streams:
                    if stream.startswith("-"):
                        req_neg = rel_or_dep(req_neg, solv.REL_OR, stream_dep(name, stream[1:]))
                    else:
                        req_pos = rel_or_dep(req_pos, solv.REL_OR, stream_dep(name, stream))

                req = pool.Dep("module(%s)" % name)
                if req_pos is not None:
                    req = req.Rel(solv.REL_WITH, req_pos)
                elif req_neg is not None:
                    req = req.Rel(solv.REL_WITHOUT, req_neg)

                require = rel_or_dep(require, solv.REL_AND, req)

            reqs = rel_or_dep(reqs, solv.REL_OR, require)

        return reqs

    def add_modules(self, mmd):
        n, s, v, c = mmd.get_name(), mmd.get_stream(), mmd.get_version(), mmd.get_context()

        pool = self.pool

        normdeps = lambda mmd, fn: [{name: streams.get()
                                     for name, streams in getattr(dep, fn)().items()}
                                    for dep in mmd.get_dependencies()]

        solvables = []
        if c is not None:
            # Built module

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

            requires = self._deps2reqs(normdeps(mmd, "get_requires"))
            solvable.add_deparray(solv.SOLVABLE_REQUIRES, requires)

            # Con: module($n)
            solvable.add_deparray(solv.SOLVABLE_CONFLICTS, pool.Dep("module(%s)" % n))

            solvables.append(solvable)
        else:
            # Input module
            # Context means two things:
            # * Unique identifier
            # * Offset for the dependency which was used
            normalized_deps = normdeps(mmd, "get_buildrequires")
            for c, deps in enumerate(mmd.get_dependencies()):
                # $n:$s:$c-$v.src
                solvable = self.build_repo.add_solvable()
                solvable.name = "%s:%s:%d:%d" % (n, s, v, c)
                solvable.evr = str(v)
                solvable.arch = "src"

                requires = self._deps2reqs([normalized_deps[c]])
                solvable.add_deparray(solv.SOLVABLE_REQUIRES, requires)

                solvables.append(solvable)

        return solvables

    def solve(self, mmd, policy=MMDResolverPolicy.First):
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

        s2nsvc = lambda s: "%s:%s" % (s.name, s.arch)
        s2ns = lambda s: ":".join(s.name.split(":", 2)[:2])

        solver = self.pool.Solver()
        alternatives = collections.OrderedDict()
        for src in solvables:
            job = self.pool.Job(solv.Job.SOLVER_INSTALL | solv.Job.SOLVER_SOLVABLE, src.id)
            requires = src.lookup_deparray(solv.SOLVABLE_REQUIRES)
            if len(requires) > 1:
                raise SystemError("At max one element should be in Requires: %s" % requires)
            elif len(requires) == 0:
                return set([frozenset([s2nsvc(src)])])

            requires = requires[0]
            src_alternatives = alternatives[src] = collections.OrderedDict()

            # TODO: replace this ugliest workaround ever with sane code of parsing rich deps.
            # We need to split them because whatprovides() treats "and" same way as "or" which is
            # not enough to generate combinations.
            # Source solvables have Req: (X and Y and Z)
            # Binary solvables have Req: ((X and Y) or (X and Z))
            # They do use "or" within "and", so simple string split won't work for binary packages.
            if src.arch != "src":
                raise NotImplementedError
            deps = str(requires).split(" and ")
            if len(deps) > 1:
                deps[0] = deps[0][1:]
                deps[-1] = deps[-1][:-1]
            deps = [self.pool.parserpmrichdep(dep) if dep.startswith("(") else self.pool.Dep(dep)
                    for dep in deps]

            for opt in itertools.product(*[self.pool.whatprovides(dep) for dep in deps]):
                log.debug("Testing %s with combination: %s", src, opt)
                if policy == MMDResolverPolicy.All:
                    kfunc = s2nsvc
                elif policy == MMDResolverPolicy.First:
                    kfunc = s2ns
                key = tuple(kfunc(s) for s in opt)
                alternative = src_alternatives.setdefault(key, [])
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
                alternative.append(newsolvables)

        if policy == MMDResolverPolicy.First:
            # Prune
            for transactions in alternatives.values():
                for ns, trans in transactions.items():
                    try:
                        transactions[ns] = [next(t for t in trans
                                                 if set(ns) <= set(s2ns(s) for s in t))]
                    except StopIteration:
                        # No transactions found for requested N:S
                        del transactions[ns]
                        continue

        return set(frozenset(s2nsvc(s) for s in transactions[0])
                   for src_alternatives in alternatives.values()
                   for transactions in src_alternatives.values())
