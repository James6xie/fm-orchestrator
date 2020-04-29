
def test_import_module(scenario, mbs):
    """
    Test import module functionality.

    Steps:
      * Request module import with scmurl provided by test.env.yaml.
    Checks:
      * Non-error response.
    """
    scmurl = scenario.get("scmurl")
    assert scmurl, "No SCM URL specified in test.env.yaml file."

    mbs.import_module(scmurl)
