import os
import sys
import shutil
import subprocess
import munch
import errno
import logging
import urlgrabber.grabber as grabber
import urlgrabber.progress as progress
from module_build_service import log


logging.basicConfig(level=logging.DEBUG)


def find_srpm(cod):
    for f in os.listdir(cod):
        if f.endswith(".src.rpm"):
            return os.path.join(cod, f)


def execute_cmd(args, stdout=None, stderr=None, cwd=None):
    """
    Executes command defined by `args`. If `stdout` or `stderr` is set to
    Python file object, the stderr/stdout output is redirecter to that file.
    If `cwd` is set, current working directory is set accordingly for the
    executed command.

    :param args: list defining the command to execute.
    :param stdout: Python file object to redirect the stdout to.
    :param stderr: Python file object to redirect the stderr to.
    :param cwd: string defining the current working directory for command.
    :raises RuntimeError: Raised when command exits with non-zero exit code.
    """
    out_log_msg = ""
    if stdout and hasattr(stdout, "name"):
        out_log_msg += ", stdout log: %s" % stdout.name
    if stderr and hasattr(stderr, "name"):
        out_log_msg += ", stderr log: %s" % stderr.name

    log.info("Executing command: %s%s" % (args, out_log_msg))
    proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, cwd=cwd)
    out, err = proc.communicate()

    if proc.returncode != 0:
        err_msg = "Command '%s' returned non-zero value %d%s" % (args, proc.returncode, out_log_msg)
        raise RuntimeError(err_msg)
    return out, err


def create_local_repo_from_koji_tag(config, tag, repo_dir, archs=None):
    """
    Downloads the packages build for one of `archs` (defaults to ['x86_64',
    'noarch']) in Koji tag `tag` to `repo_dir` and creates repository in that
    directory. Needs config.koji_profile and config.koji_config to be set.
    """

    # Placed here to avoid py2/py3 conflicts...
    import koji

    if not archs:
        archs = ["x86_64", "noarch"]

    # Load koji config and create Koji session.
    koji_config = munch.Munch(koji.read_config(
        profile_name=config.koji_profile,
        user_config=config.koji_config,
    ))

    address = koji_config.server
    log.info("Connecting to koji %r" % address)
    session = koji.ClientSession(address, opts=koji_config)

    # Get the list of all RPMs and builds in a tag.
    try:
        rpms, builds = session.listTaggedRPMS(tag, latest=True)
    except koji.GenericError:
        log.exception("Failed to list rpms in tag %r" % tag)

    # Reformat builds so they are dict with build_id as a key.
    builds = {build['build_id']: build for build in builds}

    # Prepare pathinfo we will use to generate the URL.
    pathinfo = koji.PathInfo(topdir=session.opts["topurl"])

    # Prepare the list of URLs to download
    urls = []
    for rpm in rpms:
        build_info = builds[rpm['build_id']]

        # We do not download debuginfo packages or packages built for archs
        # we are not interested in.
        if koji.is_debuginfo(rpm['name']) or not rpm['arch'] in archs:
            continue

        fname = pathinfo.rpm(rpm)
        url = pathinfo.build(build_info) + '/' + fname
        urls.append((url, os.path.basename(fname), rpm['size']))

    log.info("Downloading %d packages from Koji tag %s to %s" % (len(urls), tag, repo_dir))

    # Create the output directory
    try:
        os.makedirs(repo_dir)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

    # When True, we want to run the createrepo_c.
    repo_changed = False

    # Donload the RPMs.
    pg = progress.TextMeter(sys.stdout)
    multi_pg = progress.TextMultiFileMeter(sys.stdout)
    for url, relpath, size in urls:
        local_fn = os.path.join(repo_dir, relpath)

        # Download only when RPM is missing or the size does not match.
        if not os.path.exists(local_fn) or os.path.getsize(local_fn) != size:
            if os.path.exists(local_fn):
                os.remove(local_fn)
            repo_changed = True
            grabber.urlgrab(url, filename=local_fn, progress_obj=pg,
                            multi_progress_obj=multi_pg, async=(tag, 5),
                            text=relpath)

    grabber.parallel_wait()

    # If we downloaded something, run the createrepo_c.
    if repo_changed:
        repodata_path = os.path.join(repo_dir, "repodata")
        if os.path.exists(repodata_path):
            shutil.rmtree(repodata_path)

        log.info("Creating local repository in %s" % repo_dir)
        execute_cmd(['/usr/bin/createrepo_c', repo_dir])
