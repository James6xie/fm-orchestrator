// Build an empty module that buildrequires a virtual stream
import groovy.json.JsonOutput

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

  def testmodule = """
  document: modulemd
  version: 1
  data:
    summary: A test module in all its beautiful beauty
    description: This module buildrequires a virtual stream of the platform module
    name: testmodule
    stream: buildrequire_virtual_stream
    license:
      module: [ MIT ]
    dependencies:
      buildrequires:
          platform: fedora
      requires:
          platform: fedora
    references:
      community: https://docs.pagure.org/modularity/
      documentation: https://fedoraproject.org/wiki/Fedora_Packaging_Guidelines_for_Modules
  """

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
    writeFile file: 'buildparams.json', text: JsonOutput.toJson([modulemd: testmodule])
    krb5.withKrb {
      http_code = sh script: "curl --negotiate -u : $curlargs $url", returnStdout: true
      response = readFile file: 'response.json'
    }
  } else {
    writeFile file: 'buildparams.json', text: JsonOutput.toJson([modulemd: testmodule, owner: env.KOJI_ADMIN])
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
      def br_platform_stream = modinfo.buildrequires.platform.stream
      if (br_platform_stream != "f28") {
        echo "Module ${modinfo.id} (${modinfo.name}) buildrequires platform:${br_platform_stream}, \
          but it should buildrequire platform:f28"
        return false
      }

      echo "All checks passed"
      return true
    }
  }
}

return this;
