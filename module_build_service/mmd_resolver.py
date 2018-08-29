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
        """
        Helper method converting dependencies from MMD to solv.Dep instance expressing
        the dependencies in a way libsolv accepts as input.

        So for example for following input:
            deps = [{'gtk': ['1'], 'foo': ['1']}]
        The resulting solv.Dep expression will be:
            ((module(gtk) with module(gtk:1)) and (module(foo) with module(foo:1)))

        The "with" syntax is here to allow depending on "module(gtk)" meaning "any gtk".
        This can happen in case {'gtk': []} is used as an input.

        See the inline comments for more information.

        :param list deps: List of dicts with dependency name as key and list of streams as value.
        :rtype: solv.Dep
        :return: solv.Dep instance with dependencies in form libsolv accepts.
        """
        pool = self.pool

        # Every name:stream combination from dict in `deps` list is expressed as `solv.Dep`
        # instance and is represented internally in solv with "module(name:stream)".
        # This is parallel to RPM-world "Provides: perl(foo)" or "Requires: perl(foo)",
        # but in this method, we are only constructing the condition after the "Provides:"
        # or "Requires:".
        # This method creates such solve.Dep.
        stream_dep = lambda n, s: pool.Dep("module(%s:%s)" % (n, s))

        # There are relations between modules in `deps`. For example:
        #   deps = [{'gtk': ['1'], 'foo': ['1']}]" means "gtk:1 and foo:1" are both required.
        #   deps = [{'gtk': ['1', '2']}"] means "gtk:1 or gtk:2" are required.
        # This method helps creating such relations using following syntax:
        #   rel_or_dep(solv.Dep, solve.REL_OR, stream_dep(name, stream))
        #   rel_or_dep(solv.Dep, solve.REL_AND, stream_dep(name, stream))
        #   rel_or_dep(solv.Dep, solve.REL_WITH, stream_dep(name, stream))
        #   rel_or_dep(solv.Dep, solve.REL_WITHOUT, stream_dep(name, stream))
        rel_or_dep = lambda dep, op, rel: dep.Rel(op, rel) if dep is not None else rel

        # Check each dependency dict in `deps` list and generate the solv requirements.
        reqs = None
        for dep_dicts in deps:
            # Contains the solv.Dep requirements for current dict.
            require = None
            for name, streams in dep_dicts.items():
                # The req_pos will store solv.Dep expression for "positive" requirements.
                # That is the case of 'gtk': ['1', '2'].
                # The req_neg will store negative requirements like 'gtk': ['-1', '-2'].
                req_pos = req_neg = None

                # For each stream in `streams` for this dependency, generate the
                # module(name:stream) solv.Dep and add REL_OR relations between them.
                for stream in streams:
                    if stream.startswith("-"):
                        req_neg = rel_or_dep(req_neg, solv.REL_OR, stream_dep(name, stream[1:]))
                    else:
                        req_pos = rel_or_dep(req_pos, solv.REL_OR, stream_dep(name, stream))

                # Generate the module(name) solv.Dep.
                req = pool.Dep("module(%s)" % name)

                # Use the REL_WITH for positive requirements and REL_WITHOUT for negative
                # requirements.
                if req_pos is not None:
                    req = req.Rel(solv.REL_WITH, req_pos)
                elif req_neg is not None:
                    req = req.Rel(solv.REL_WITHOUT, req_neg)

                # And in the end use AND between the last name:[streams] and the current one.
                require = rel_or_dep(require, solv.REL_AND, req)

            # There might be multiple dicts in `deps` list, so use OR relation between them.
            reqs = rel_or_dep(reqs, solv.REL_OR, require)

        return reqs

    def add_modules(self, mmd):
        """
        Adds module represented by `mmd` metadata to MMDResolver. Modules added by this
        method will be considered as possible dependencies while resolving the dependencies
        using the `solve(...)` method only if their "context" is None. Otherwise they are
        treated like input modules we want to resolve dependencies for.

        :param Modulemd mmd: Metadata of module to add.
        :rtype: list
        :return: list of solv.Solvable instances representing the module in libsolv world.
        """
        n, s, v, c = mmd.get_name(), mmd.get_stream(), mmd.get_version(), mmd.get_context()
        pool = self.pool

        # Helper method to return the dependencies of `mmd` in the {name: [streams], ... form}.
        # The `fn` is either "get_requires" or "get_buildrequires" str depending on whether
        # the return deps should be runtime requires or buildrequires.
        normdeps = lambda mmd, fn: [{name: streams.get()
                                     for name, streams in getattr(dep, fn)().items()}
                                    for dep in mmd.get_dependencies()]

        # Each solvable object has name, version, architecture and list of
        # provides/requires/conflicts which defines its relations with other solvables.
        # You can imagine solvable as a single RPM.
        # Single module can be represented by multiple solvables - read further inline
        # comments for more info. Therefore we use list to store them.
        solvables = []
        if c is not None:
            # If context is not set, the module we are adding should be used as dependencies
            # for input module. Therefore add it in "available_repo".
            solvable = self.available_repo.add_solvable()

            # Use n:s:v:c as name, version as version and set the arches.
            solvable.name = "%s:%s:%d:%s" % (n, s, v, c)
            solvable.evr = str(v)
            # TODO: replace with real arch, but for now resolving using single arch
            # is sufficient.
            solvable.arch = "x86_64"

            # Add "Provides: module(name)", each module provides itself.
            # This is used for example to find the buildrequired module when
            # no particular stream is used - for example when buildrequiring
            # "gtk: []"
            solvable.add_deparray(solv.SOLVABLE_PROVIDES,
                                  pool.Dep("module(%s)" % n))
            # Add "Provides: module(name:stream) = version", so we can find builrequired
            # modules when "gtk:[1]" is used and also choose the latest version.
            solvable.add_deparray(solv.SOLVABLE_PROVIDES,
                                  pool.Dep("module(%s:%s)" % (n, s)).Rel(
                                      solv.REL_EQ, pool.Dep(str(v))))

            # Fill in the "Requires" of this module, so we can track its dependencies
            # on other modules.
            requires = self._deps2reqs(normdeps(mmd, "get_requires"))
            solvable.add_deparray(solv.SOLVABLE_REQUIRES, requires)

            # Add "Conflicts: module(name)", because TODO, ask ignatenko.
            solvable.add_deparray(solv.SOLVABLE_CONFLICTS, pool.Dep("module(%s)" % n))
            solvables.append(solvable)
        else:
            # For input module, we might have multiple buildrequires/requires pairs in the
            # input `mmd`. For example like this:
            #   - buildrequires:
            #       gtk: [1]
            #       platform: [f28]
            #     requires:
            #       gtk: [1]
            #   - buildrequires:
            #       gtk: [2]
            #       platform: [f29]
            #     requires:
            #       gtk: [2]
            # This means we need: "(gtk:1 and platform:f28) or (gtk:2 and platform:f29)".
            # There is no way how to express that in libsolv as single solvable and in the same
            # time try all the possible combinations. Libsolv just returns the single one and does
            # not offer enough data for us to tell it to try another one to really find all of
            # them.
            # The solution for that is therefore adding multiple solvables for each OR block of
            # that input condition.
            #
            # So in our example, we add two solvables:
            #   1) Solvable with name "n:s:v:0" and "Requires: gtk:1 and platform:f28".
            #   2) Solvable with name "n:s:v:1" and "Requires: gtk:2 and platform:f29".
            #
            # Note the "context" field in the solvable name - it is set according to index
            # of buildrequires/requires pair and uniquely identifies the Solvable.
            #
            # Using this trick, libsolv will try to solve all the buildrequires/requires pairs,
            # because they are expressed as separate Solvables and we are able to distinguish
            # between them thanks to context value.
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

        :param Modulemd mmd: Input modulemd which should have the `context` set
            to None.
        :param policy: Policy to use when the dependencies used in buildrequires
            section are ambigous. For example, when the single buildrequired
            module is gtk:1 and this gtk:1 module is built against both
            platform:f28 and platform:f29, the policy influences the resolving
            in following way:

            - MMDResolverPolicy.First: Only single combination of buildrequires
              will be returned with "gtk:1" and "platform:f28", because the input
              buildrequires section did not mention any platform stream and
              therefore "first one" is used.
            - MMDResolverPolicy.All: Two combinations of buildrequires will be returned,
              one with "gtk:1" and "platform:f28", other with "gtk:1" and "platform:f29".

        :return: set of frozensets of n:s:v:c of modules which satisfied the
            dependency solving.
        """
        # Add the input module to pool and generate the "Provides" data so we can
        # use them for resolving later.
        solvables = self.add_modules(mmd)
        if not solvables:
            raise ValueError("No module(s) found for resolving")
        self.pool.createwhatprovides()

        # "solvable to n:s:v:c"
        s2nsvc = lambda s: "%s:%s" % (s.name, s.arch)
        # "solvable to n:s"
        s2ns = lambda s: ":".join(s.name.split(":", 2)[:2])

        # For each solvable object generated from input module, run the solver.
        # For reasons why there might be multiple solvable objects, please read the
        # `add_modules(...)` inline comments.
        solver = self.pool.Solver()
        alternatives = collections.OrderedDict()
        for src in solvables:
            # Create the solv Job to represent the solving task.
            job = self.pool.Job(solv.Job.SOLVER_INSTALL | solv.Job.SOLVER_SOLVABLE, src.id)

            # Check that at max 1 requires element exists in the solvable object - since
            # we create multiple solvable objects where each of them has at max one
            # requires element, it should never be the case...
            # NOTE: "requires" in solvable are actually "buildrequires" in mmd.
            requires = src.lookup_deparray(solv.SOLVABLE_REQUIRES)
            if len(requires) > 1:
                raise SystemError("At max one element should be in Requires: %s" % requires)
            elif len(requires) == 0:
                # Return early in case the requires is empty, because it basically means
                # the module has no buildrequires section.
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

            # What we get in `requires` here is a string in following format:
            #   ((module(gtk) with module(gtk:1)) and (module(foo) with module(foo:1)) and (...))
            # And what we want to get is the list of all valid combinations with particular NSVCs
            # of buildrequired modules. There are few steps we need to do to achieve that:

            # 1) Convert the "(R1 and R2 and R3)" string to list of solv.Dep in following format:
            #    [solv.Dep(R1), solv.Dep(R2), solv.Dep(R3), ...]
            deps = str(requires).split(" and ")
            if len(deps) > 1:
                # Remove the extra parenthesis in the input string in case there are more
                # rules.
                deps[0] = deps[0][1:]
                deps[-1] = deps[-1][:-1]
            # Generate the new deps using the parserpmrichdep.
            deps = [self.pool.parserpmrichdep(dep) if dep.startswith("(") else self.pool.Dep(dep)
                    for dep in deps]

            # 2) For each dep (name:stream), get the set of all solvables in particular NSVCs,
            #    which provides that name:stream. Then use itertools.product() to actually
            #    generate all the possible combinations so we can try solving them.
            for opt in itertools.product(*[self.pool.whatprovides(dep) for dep in deps]):
                log.debug("Testing %s with combination: %s", src, opt)
                # We will be trying to solve all the combinations using all the NSVCs
                # we have in pool, but as we said earlier, we don't want to return
                # all of them when MMDResolverPolicy.First is used.
                # We will achieve that by storing alternative combinations in `src_alternatives`
                # with NSVC as key in case we want all of them and NS as a key when we want
                # just First combination for given dependency.
                # This will allow us to group alternatives for single NS in case of First
                # policy and later return just the first alternative.
                if policy == MMDResolverPolicy.All:
                    kfunc = s2nsvc
                elif policy == MMDResolverPolicy.First:
                    kfunc = s2ns
                key = tuple(kfunc(s) for s in opt)
                # `key` now contains tuple similar to "('gtk:1', 'foo:1')"
                alternative = src_alternatives.setdefault(key, [])

                # Create the solving jobs.
                # We need to say to libsolv that we want it to prefer modules from the combination
                # we are currently trying, otherwise it would just choose some random ones.
                # We do that by FAVORING those modules - this is done in libsolv by another
                # job prepending to our main job to resolve the deps of input module.
                jobs = [self.pool.Job(solv.Job.SOLVER_FAVOR | solv.Job.SOLVER_SOLVABLE, s.id)
                        for s in opt] + [job]

                # Log the job.
                log.debug("Jobs:")
                for j in jobs:
                    log.debug("  - %s", j)
                # Solve the deps and log the dependency issues.
                problems = solver.solve(jobs)
                if problems:
                    raise RuntimeError("Problems were found during solve(): %s" % ", ".join(
                                       str(p) for p in problems))
                # Find out what was actually resolved by libsolv to be installed as a result
                # of our jobs - those are the modules we are looking for.
                newsolvables = solver.transaction().newsolvables()
                log.debug("Transaction:")
                for s in newsolvables:
                    log.debug("  - %s", s)
                # Append them as an alternative for this src_alternative.
                # Remember that src_alternatives are grouped by NS or NSVC depending on
                # MMDResolverPolicy, so there might be more of them.
                alternative.append(newsolvables)

        # If the MMDResolverPolicy is First, we will check all the alternatives and keep
        # just the "first" one.
        if policy == MMDResolverPolicy.First:
            # Prune
            for transactions in alternatives.values():
                for ns, trans in transactions.items():
                    try:
                        # The transation to keep is defined by the name:stream comparison,
                        # so we always return the same name:stream if the input is the same.
                        transactions[ns] = [next(t for t in trans
                                                 if set(ns) <= set(s2ns(s) for s in t))]
                    except StopIteration:
                        # No transactions found for requested N:S
                        del transactions[ns]
                        continue

        # Convert the solvables in alternatives to nsvc and return them as set of frozensets.
        return set(frozenset(s2nsvc(s) for s in transactions[0])
                   for src_alternatives in alternatives.values()
                   for transactions in src_alternatives.values())
