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
from module_build_service import log, conf
import itertools

class MMDResolver(object):
    """
    Resolves dependencies between Module metadata objects.
    """

    def __init__(self):
        self.pool = solv.Pool()
        self.pool.setarch("x86_64")
        self.build_repo = self.pool.add_repo("build")
        self.available_repo = self.pool.add_repo("available")

        self.solvables_per_name = {}
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
        solvable.add_provides(
            self.pool.Dep("module(%s)" % solvable.name).Rel(
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
        if mmd.get_name() not in self.solvables_per_name:
            self.solvables_per_name[mmd.get_name()] = []
        for other_solvable in self.solvables_per_name[mmd.get_name()]:
            other_solvable.add_conflicts(
                self.pool.Dep("module(%s)" % solvable.name).Rel(
                    solv.REL_EQ, self.pool.Dep(solvable.evr)))
            solvable.add_conflicts(
                self.pool.Dep("module(%s)" % other_solvable.name).Rel(
                    solv.REL_EQ, self.pool.Dep(other_solvable.evr)))
        self.solvables_per_name[mmd.get_name()].append(solvable)

        return solvable

    def add_available_module(self, mmd):
        """
        Adds module available for dependency solving.
        """
        self._create_solvable(self.available_repo, mmd)

    def _solve(self, module_name, alternative_with=None):
        """
        Solves the dependencies of module `module_name`. If there is an
        alternative solution to dependency solving, it will prefer the one
        which brings in the package in `alternative_with` list (if set).

        :rtype: solv.Solver
        :return: Solver object with dependencies resolved.
        """
        solver = self.pool.Solver()
        # Try to select the module we are interested in.
        flags = solv.Selection.SELECTION_PROVIDES
        sel = self.pool.select("module(%s)" % module_name, flags)
        if sel.isempty():
            raise ValueError(
                "Cannot find module %s while resolving "
                "dependencies" % module_name)
        # Prepare the job including the solution for problems from previous calls.
        jobs = sel.jobs(solv.Job.SOLVER_INSTALL)

        if alternative_with:
            for name in alternative_with:
                sel = self.pool.select("module(%s)" % name, flags)
                if sel.isempty():
                    raise ValueError(
                        "Cannot find module %s while resolving "
                        "dependencies" % name)
                jobs += sel.jobs(solv.Job.SOLVER_FAVOR)
        # Try to solve the dependencies.
        problems = solver.solve(jobs)
        # In case we have some problems, return early here with the problems.
        if len(problems) != 0:
            # TODO: Add more info.
            raise ValueError(
                "Dependencies between modules are not satisfied")
        return solver

    def _solve_recurse(self, solvable, alternatives=None, alternatives_tried=None):
        """
        Solves dependencies of module defined by `solvable` object and all its
        alternatives recursively.

        :return: set of frozensets of n:s:v:c of modules which satisfied the
            dependency solving.
        """
        if not alternatives:
            alternatives = set()
        if not alternatives_tried:
            alternatives_tried = set()

        solver = self._solve(solvable.name, alternatives)
        if not solver:
            return set([])

        ret = set([])
        ret.add(
            frozenset([s.name for s in solver.transaction().newsolvables()
                    if s.name != solvable.name]))

        choices = []
        for alt in solver.all_alternatives():
            l = []
            for alt_choice in alt.choices():
                if alt_choice.name.split(":")[0] in self.alternatives_whitelist:
                    l.append(alt_choice.name)
            if l:
                choices.append(l)

        choices_combinations = list(itertools.product(*choices))
        for choices_combination in choices_combinations:
            if choices_combination not in alternatives_tried:
                alternatives_tried.add(choices_combination)
                ret = ret.union(self._solve_recurse(
                    solvable, choices_combination, alternatives_tried))

        return ret

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

        alternatives = self._solve_recurse(solvable)
        return alternatives
