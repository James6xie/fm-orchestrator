import os
import koji
import tempfile
import shutil
import subprocess
import logging
import module_build_service
from module_build_service import log, scm


logging.basicConfig(level=logging.DEBUG)


def build_from_scm(artifact_name, source, config, build_srpm,
                   data = None, stdout=None, stderr=None):
    """
    Builds the artifact from the SCM based source.

    :param artifact_name: Name of the artifact.
    :param source: SCM URL with artifact's sources (spec file).
    :param config: Config instance.
    :param build_srpm: Method to call to build the RPM from the generate SRPM.
    :param data: Data to be passed to the build_srpm method.
    :param stdout: Python file object to which the stdout of SRPM build
                   command is logged.
    :param stderr: Python file object to which the stderr of SRPM build
                   command is logged.
    """
    ret = (0, koji.BUILD_STATES["FAILED"], "Cannot create SRPM", None)
    td = None

    try:
        log.debug('Cloning source URL: %s' % source)
        # Create temp dir and clone the repo there.
        td = tempfile.mkdtemp()
        scm = module_build_service.scm.SCM(source)
        cod = scm.checkout(td)

        # Use configured command to create SRPM out of the SCM repo.
        log.debug("Creating SRPM in %s" % cod)
        _execute_cmd(config.mock_build_srpm_cmd.split(" "),
                     stdout=stdout, stderr=stderr, cwd=cod)

        # Find out the built SRPM and build it normally.
        for f in os.listdir(cod):
            if f.endswith(".src.rpm"):
                log.info("Created SRPM %s" % f)
                source = os.path.join(cod, f)
                ret = build_srpm(artifact_name, source, data)
                break
    except Exception as e:
        log.error("Error while generating SRPM for artifact %s: %s" % (
            artifact_name, str(e)))
        ret = (0, koji.BUILD_STATES["FAILED"], "Cannot create SRPM %s" % str(e), None)
    finally:
        try:
            if td is not None:
                shutil.rmtree(td)
        except Exception as e:
            log.warning(
                "Failed to remove temporary directory {!r}: {}".format(
                    td, str(e)))

    return ret


def _execute_cmd(args, stdout = None, stderr = None, cwd = None):
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
    if stdout:
        out_log_msg += ", stdout log: %s" % stdout.name
    if stderr:
        out_log_msg += ", stderr log: %s" % stderr.name

    log.info("Executing command: %s%s" % (args, out_log_msg))
    proc = subprocess.Popen(args, stdout=stdout, stderr=stderr, cwd=cwd)
    proc.communicate()

    if proc.returncode != 0:
        err_msg = "Command '%s' returned non-zero value %d%s" % (args, proc.returncode, out_log_msg)
        raise RuntimeError(err_msg)
