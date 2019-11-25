// Submit a build to MBS and verify that it initializes Koji correctly

def runTests() {
  def koji_admin = controller.getVar('KOJI_ADMIN')
  def clientcert = controller.httpGet("/ca/${koji_admin}", true)
  def koji_ssl_host = controller.getVar('KOJI_HUB_HOST')
  def mbs_host = controller.getVar('MBS_FRONTEND_HOST')
  def ca_cert = controller.httpGet("/ca/cacert")
  koji.setConfig("https://${koji_ssl_host}/kojihub",
                 "https://${koji_ssl_host}/kojifiles",
                 clientcert.cert, clientcert.key, ca_cert)
  def tags = koji.callMethod("listTags")
  if (!tags.any { it.name == "module-f28" }) {
    koji.addTag("module-f28")
  }
  if (!tags.any { it.name == "module-f28-build" }) {
    koji.addTag("module-f28-build", "--parent=module-f28", "--arches=x86_64")
  }
  writeFile file: 'ca-cert.pem', text: ca_cert
  def url = "https://${mbs_host}/module-build-service/1/module-builds/"
  def curlargs = """
    --cacert ca-cert.pem \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json' \
    -d @buildparams.json \
    -o response.json \
    -w '%{http_code}'
  """.trim()
  def http_code, response
  if (controller.getVar("KRB5_REALM")) {
    writeFile file: 'buildparams.json', text: """
      {"scmurl": "https://src.fedoraproject.org/modules/testmodule.git?#9c589780e1dd1698dc64dfa28d30014ad18cad32",
       "branch": "f28"}
    """
    krb5.withKrb(controller.getKrb5Vars(koji_admin)) {
      http_code = sh script: "curl --negotiate -u : $curlargs $url", returnStdout: true
      response = readFile file: 'response.json'
    }
  } else {
    writeFile file: 'buildparams.json', text: """
      {"scmurl": "https://src.fedoraproject.org/modules/testmodule.git?#9c589780e1dd1698dc64dfa28d30014ad18cad32",
       "branch": "f28",
       "owner":  "${koji_admin}"}
    """
    http_code = sh script: "curl $curlargs $url", returnStdout: true
    response = readFile file: 'response.json'
  }
  if (http_code != '201') {
    echo "Response code was ${http_code}, output was ${response}"
    error "POST response code was ${http_code}, not 201"
  }
  def buildinfo = readJSON(text: response)
  // Check that MBS has configured Koji correctly
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
      } else if (modinfo.state_name != "build") {
        echo "Module ${modinfo.id} (${modinfo.name}) is in the ${modinfo.state_name} state, not build"
        return false
      }
      def targets = koji.listTargets()
      def target = targets.find { it.name =~ "^module-testmodule-" }
      if (!target) {
        echo "Could not find module target"
        return false
      }
      echo "Target: ${target}"
      def taginfo = koji.tagInfo(target.build_tag_name)
      echo "Build tag: ${taginfo}"
      if (taginfo.arches != "x86_64") {
        echo "${target.build_tag_name} does not have arches set to x86_64"
        return false
      }
      if (taginfo.perm != "admin") {
        echo "${target.build_tag_name} does not have perm set to admin"
        return false
      }
      if (taginfo.extra.get("mock.package_manager", "") != "dnf") {
        echo "${target.build_tag_name} is not configured to use dnf"
        return false
      }
      if (!taginfo.extra.get("repo_include_all", false)) {
        echo "${target.build_tag_name} is not configured with repo_include_all"
        return false
      }
      def ancestors = koji.listTagInheritance(target.build_tag_name)
      echo "Ancestors of ${target.build_tag_name}: ${ancestors}"
      if (!ancestors.contains("module-f28-build")) {
        echo "module-f28-build not in inheritance of ${target.build_tag_name}"
        return false
      }
      def groups = koji.listGroups(target.build_tag_name)
      echo "Groups of ${target.build_tag_name}: ${groups}"
      def srpm_build = groups.find { it.name == "srpm-build" }
      if (!srpm_build) {
        echo "${target.build_tag_name} does not have an srpm-build group"
        return false
      }
      def srpm_packages = srpm_build.packagelist.findAll { it.package in ["bash", "rpm-build", "module-build-macros"] }
      if (srpm_packages.size() != 3) {
        echo "${target.build_tag_name} does not have required packages in the srpm-build group"
        return false
      }
      def build = groups.find { it.name == "build" }
      if (!build) {
        echo "${target.build_tag_name} does not have a build group"
        return false
      }
      def build_packages = build.packagelist.findAll { it.package in ["bash", "rpm-build", "module-build-macros"] }
      if (build_packages.size() != 3) {
        echo "${target.build_tag_name} does not have required packages in the build group"
        return false
      }
      def tasks = koji.listTasks()
      echo "Tasks: ${tasks}"
      def build_task = tasks.find { it.method == "build" }
      if (!build_task) {
         echo "No build task has been created"
         return false
      }
      if (build_task.request.size() < 3) {
        echo "The build task does not have the correct format"
        return false
      }
      if (!build_task.request[0].contains("module-build-macros")) {
        echo "The build task is not building module-build-macros"
        return false
      }
      if (!build_task.request[0].endsWith(".src.rpm")) {
        echo "The build task is not building from an SRPM"
        return false
      }
      if (build_task.request[1] != target.name) {
        echo "The build task is not using the correct target"
        return false
      }
      if (!build_task.request[2].get("skip_tag", false)) {
        echo "The build task is not using skip_tag"
        return false
      }
      if (build_task.request[2].get("mbs_artifact_name", "") != "module-build-macros") {
        echo "The build task does not have the mbs_artifact_name option set correctly"
        return false
      }
      if (build_task.request[2].get("mbs_module_target", "") != target.dest_tag_name) {
        echo "The build task does not have the mbs_module_target option set correctly"
        return false
      }
      def newrepo_task = tasks.find { it.method == "newRepo" }
      if (!newrepo_task) {
        echo "No newRepo task has been created"
        return false
      }
      if (newrepo_task.request.size() < 1) {
        echo "The newRepo task does not have the correct format"
        return false
      }
      if (newrepo_task.request[0] != target.build_tag_name) {
        echo "The newRepo task is not associated with the correct tag"
        return false
      }
      echo "All checks passed"
      return true
    }
  }
}

return this;
