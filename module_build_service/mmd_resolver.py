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

import solv
from module_build_service import log


def _gather_alternatives(pool, favor=None, tested=None, level=1, transactions=None):
    if tested is None:
        tested = set()
    if transactions is None:
        transactions = []
    solver = pool.Solver()

    jobs = []
    jobs.extend(pool.Job(solv.Job.SOLVER_FAVOR | solv.Job.SOLVER_SOLVABLE, s.id)
                for s in favor or [])
    jobs.extend(pool.Job(solv.Job.SOLVER_DISFAVOR | solv.Job.SOLVER_SOLVABLE, s.id)
                for s in tested)
    problems = solver.solve(jobs)
    if problems:
        raise RuntimeError("Problems were found during solve(): %s" % ", ".join(
            str(p) for p in problems))
    newsolvables = solver.transaction().newsolvables()
    transactions.append(newsolvables)
    alternatives = solver.all_alternatives()
    if not alternatives:
        return transactions

    if [alt for alt in alternatives if alt.type != solv.Alternative.SOLVER_ALTERNATIVE_TYPE_RULE]:
        raise SystemError("Encountered alternative with type != rule")

    log.debug("Jobs:")
    for job in pool.getpooljobs():
        log.debug("  * %s [pool]", job)
    for job in jobs:
        log.debug("  * %s", job)
    log.debug("Transaction:")
    for s in newsolvables:
        log.debug("  * %s", s)
    log.debug("Alternatives:")
    auto_minimized = False
    for alt in alternatives:
        raw_choices = alt.choices_raw()
        log.debug("  %d: %s", alt.level, alt)
        for choice in alt.choices():
            if choice == alt.chosen:
                sign = "+"
            elif -choice.id in raw_choices:
                sign = "-"
                auto_minimized = True
            else:
                sign = " "
            log.debug("  * %s%s", sign, choice)
    if auto_minimized:
        raise NotImplementedError("Transaction was auto-minimized")

    current_alternatives = [alt for alt in alternatives if alt.level == level]
    if len(current_alternatives) > 1:
        raise SystemError("Encountered multiple alternatives on the same level")

    alternative = current_alternatives[0]
    raw_choices = alternative.choices_raw()
    tested.add(alternative.chosen)

    for choice in (choice for choice in alternative.choices() if choice not in tested):
        _gather_alternatives(pool,
                             favor=favor,
                             tested=tested,
                             level=level,
                             transactions=transactions)

    max_level = max(alt.level for alt in alternatives)
    if level == max_level:
        return transactions

    next_favor = [alt.chosen for alt in alternatives if alt.level <= level]
    next_tested = set(alt.chosen for alt in alternatives if alt.level == level + 1)
    _gather_alternatives(pool,
                         favor=next_favor,
                         tested=next_tested,
                         level=level + 1,
                         transactions=transactions)

    return transactions


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

            # $n:$s:$c-$v.$a
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
                solvable.name = "%s:%s:%s:%d" % (n, s, v, c)
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

        # XXX: Using SOLVABLE_ONE_OF should be faster & more convenient.
        # There must be a bug in _gather_alternatives(), possibly when processing l1 alternatives.
        # Use pool.towhatprovides() to combine solvables.

        alternatives = []
        jobs = self.pool.getpooljobs()
        for s in solvables:
            new_job = self.pool.Job(solv.Job.SOLVER_INSTALL | solv.Job.SOLVER_SOLVABLE, s.id)
            self.pool.setpooljobs(jobs + [new_job])
            alternatives.extend(_gather_alternatives(self.pool))
        self.pool.setpooljobs(jobs)

        return set(frozenset("%s:%s" % (s.name, s.arch) for s in trans)
                   for trans in alternatives)
