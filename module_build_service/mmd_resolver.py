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
    assert not solver.solve(jobs)
    newsolvables = solver.transaction().newsolvables()
    transactions.append(newsolvables)
    alternatives = solver.all_alternatives()
    if not alternatives:
        return transactions

    if [alt for alt in alternatives if alt.type != solv.Alternative.SOLVER_ALTERNATIVE_TYPE_RULE]:
        assert False, "Recommends alternative rule"

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
        raise NotImplementedError

    current_alternatives = [alt for alt in alternatives if alt.level == level]
    if len(current_alternatives) > 1:
        raise NotImplementedError

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

        self.alternatives_whitelist = set()

    def _create_solvable(self, repo, mmd):
        """
        Creates libsolv Solvable object in repo `repo` based on the Modulemd
        metadata `mmd`.

        This fills in all the provides/requires/conflicts of Solvable.

        :rtype: solv.Solvable
        :return: Solvable object.
        """
        solvable = repo.add_solvable()
        solvable.name = "%s:%s:%d:%s" % (mmd.get_name(), mmd.get_stream(),
                                         mmd.get_version(), mmd.get_context())
        solvable.evr = "%s-%d" % (mmd.get_stream(), mmd.get_version())
        solvable.arch = "x86_64"

        # Provides
        solvable.add_provides(
            self.pool.Dep("module(%s)" % mmd.get_name()).Rel(
                solv.REL_EQ, self.pool.Dep(solvable.evr)))

        # Requires
        for deps in mmd.get_dependencies():
            for name, streams in deps.get_requires().items():
                requires = None
                for stream in streams.get():
                    require = self.pool.Dep("module(%s)" % name)
                    require = require.Rel(solv.REL_EQ, self.pool.Dep(stream))
                    if requires:
                        requires = requires.Rel(solv.REL_OR, require)
                    else:
                        requires = require
                solvable.add_requires(requires)

        # Build-requires in case we are in build_repo.
        if repo == self.build_repo:
            solvable.arch = "src"
            for deps in mmd.get_dependencies():
                for name, streams in deps.get_buildrequires().items():
                    requires = None
                    for stream in streams.get():
                        require = self.pool.Dep("module(%s)" % name)
                        require = require.Rel(solv.REL_EQ, self.pool.Dep(stream))
                        if requires:
                            requires = requires.Rel(solv.REL_OR, require)
                        else:
                            requires = require
                    solvable.add_requires(requires)
                    self.alternatives_whitelist.add(name)

        # Conflicts
        solvable.add_conflicts(self.pool.Dep("module(%s)" % mmd.get_name()))

        return solvable

    def add_available_module(self, mmd):
        """
        Adds module available for dependency solving.
        """
        self._create_solvable(self.available_repo, mmd)

    def solve(self, mmd):
        """
        Solves dependencies of module defined by `mmd` object. Returns set
        containing frozensets with all the possible combinations which
        satisfied dependencies.

        :return: set of frozensets of n:s:v:c of modules which satisfied the
            dependency solving.
        """
        solvable = self._create_solvable(self.build_repo, mmd)
        self.pool.createwhatprovides()

        new_job = self.pool.Job(solv.Job.SOLVER_INSTALL | solv.Job.SOLVER_SOLVABLE, solvable.id)
        jobs = self.pool.getpooljobs()
        self.pool.setpooljobs(jobs + [new_job])
        alternatives = _gather_alternatives(self.pool)
        self.pool.setpooljobs(jobs)

        return set(frozenset(s.name for s in trans if s != solvable) for trans in alternatives)
