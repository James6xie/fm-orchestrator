// Build an empty module and verify that the CGImport works correctly

def runTests() {
  def clientcert = ca.get_ssl_cert(env.KOJI_ADMIN)
  koji.setConfig("https://${env.KOJI_SSL_HOST}/kojihub", "https://${env.KOJI_SSL_HOST}/kojifiles",
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
    koji.runCmd("grant-cg-access", env.KOJI_ADMIN, "module-build-service", "--new")
  } catch (ex) {
    echo "Granting cg-access to ${env.KOJI_ADMIN} failed, assuming it was already provided in a previous test"
  }

  if (!koji.callMethod("listBTypes").any { it.name == "module" }) {
    koji.callMethodLogin("addBType", "module")
  }

  writeFile file: 'ca-cert.pem', text: ca.get_ca_cert().cert
  def url = "https://${env.MBS_SSL_HOST}/module-build-service/1/module-builds/"
  def curlargs = """
    --cacert ca-cert.pem \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -d @buildparams.json \
    -o response.json \
    -w '%{http_code}'
  """.trim()
  def http_code, response
  if (env.KRB5_REALM) {
    writeFile file: 'buildparams.json', text: """
      {"scmurl": "https://src.fedoraproject.org/forks/mikeb/modules/testmodule.git?#8b3fb16160f899ce10905faf570f110d52b91154",
       "branch": "empty-f28"}
    """
    krb5.withKrb {
      http_code = sh script: "curl --negotiate -u : $curlargs $url", returnStdout: true
      response = readFile file: 'response.json'
    }
  } else {
    writeFile file: 'buildparams.json', text: """
      {"scmurl": "https://src.fedoraproject.org/forks/mikeb/modules/testmodule.git?#8b3fb16160f899ce10905faf570f110d52b91154",
       "branch": "empty-f28",
       "owner":  "${env.KOJI_ADMIN}"}
    """
    http_code = sh script: "curl $curlargs $url", returnStdout: true
    response = readFile file: 'response.json'
  }
  if (http_code != '201') {
    echo "Response code was ${http_code}, output was ${response}"
    error "POST response code was ${http_code}, not 201"
  }
  def buildinfo = readJSON(text: response)
  timeout(10) {
    waitUntil {
      def resp = httpRequest url: "${url}${buildinfo.id}", ignoreSslErrors: true
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
