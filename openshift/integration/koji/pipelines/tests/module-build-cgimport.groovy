// Build an empty module and verify that the CGImport works correctly

def runTests() {
  def clientcert = ca.get_ssl_cert("mbs-${TEST_ID}-koji-admin")
  koji.setConfig("https://koji-${TEST_ID}-hub/kojihub", "https://koji-${TEST_ID}-hub/kojifiles",
                 clientcert.cert, clientcert.key, ca.get_ca_cert().cert)
  def tags = koji.callMethod("listTags")
  if (!tags.any { it.name == "module-f28" }) {
    koji.addTag("module-f28")
  }
  if (!tags.any { it.name == "module-f28-build" }) {
    koji.addTag("module-f28-build", "--parent=module-f28", "--arches=x86_64")
  }
  try {
    // There's currently no way to query whether a given user has CG access, so just add it
    // and hope no one else has already done it.
    koji.runCmd("grant-cg-access", "mbs-${TEST_ID}-koji-admin", "module-build-service", "--new")
  } catch (ex) {
    echo "Granting cg-access to mbs-${TEST_ID}-koji-admin failed, assuming it was already provided in a previous test"
  }

  if (!koji.callMethod("listBTypes").any { it.name == "module" }) {
    koji.callMethodLogin("addBType", "module")
  }

  def buildparams = """
        {"scmurl": "https://src.fedoraproject.org/forks/mikeb/modules/testmodule.git?#8b3fb16160f899ce10905faf570f110d52b91154",
         "branch": "empty-f28",
         "owner":  "mbs-${TEST_ID}-koji-admin"}
      """
  def resp = httpRequest(
        httpMode: "POST",
        url: "https://mbs-${TEST_ID}-frontend/module-build-service/1/module-builds/",
        acceptType: "APPLICATION_JSON",
        contentType: "APPLICATION_JSON",
        requestBody: buildparams,
        ignoreSslErrors: true,
      )
  if (resp.status != 201) {
    echo "Response code was ${resp.status}, output was ${resp.content}"
    error "POST response code was ${resp.status}, not 201"
  }
  def buildinfo = readJSON(text: resp.content)
  timeout(10) {
    waitUntil {
      resp = httpRequest(
        url: "https://mbs-${TEST_ID}-frontend/module-build-service/1/module-builds/${buildinfo.id}",
        ignoreSslErrors: true,
      )
      if (resp.status != 200) {
        echo "Response code was ${resp.status}, output was ${resp.content}"
        error "GET response code was ${resp.status}, not 200"
      }
      def modinfo = readJSON(text: resp.content)
      if (modinfo.state_name == "failed") {
        error "Module ${modinfo.id} (${modinfo.name}) is in the ${modinfo.state_name} state"
      } else if (modinfo.state_name != "ready") {
        echo "Module ${modinfo.id} (${modinfo.name}) is in the ${modinfo.state_name} state, not ready"
        return false
      }
      def builds = koji.listBuilds()
      echo "Builds: ${builds}"
      def build = builds.find { it.name == "testmodule" }
      if (!build) {
        echo "Could not find a build of testmodule"
        return false
      }
      def develbuild = builds.find { it.name == "testmodule-devel" }
      if (!develbuild) {
        echo "Could not find a build of testmodule-devel"
        return false
      }
      echo "All checks passed"
      return true
    }
  }
}

return this;
