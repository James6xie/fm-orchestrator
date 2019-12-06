{% include "snippets/c3i-library.groovy" %}
pipeline {
  {% include "snippets/default-agent.groovy" %}
  options {
    timestamps()
    timeout(time: 120, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '10'))
  }
  triggers {
    ciBuildTrigger(
      noSquash: false,
      providerList: [
        activeMQSubscriber(
          name: params.MESSAGING_PROVIDER,
          overrides: [topic: params.MESSAGING_TOPIC],
          selector: "repo = '${params.TRACKED_CONTAINER_REPO}' AND action IN ('added', 'updated') AND tag = '${params.TRACKED_TAG}'",
        )
      ]
    )
  }
  stages {
    stage("Message Check and setup") {
      steps {
        script {
          if (!params.CI_MESSAGE) {
            error("This build is not started by a CI message. Only configurations were done.")
          }
          c3i.clone(repo: params.MBS_GIT_REPO, branch: params.MBS_GIT_REF)
          def message = readJSON text: params.CI_MESSAGE
          echo "Tag :${message.tag} is ${message.action} in ${message.repo}. New digest: ${message.digest}"
          env.FRONTEND_IMAGE_REF = "${message.repo}@${message.digest}"
          // We have the digest of the current frontend image with this tag.
          // Lookup the digest of the current backend image with the same tag.
          if (params.CONTAINER_REGISTRY_CREDENTIALS) {
            dir ("${env.HOME}/.docker") {
              openshift.withCluster() {
                def dockerconf = openshift.selector('secret', params.CONTAINER_REGISTRY_CREDENTIALS).object().data['.dockerconfigjson']
                writeFile file: 'config.json', text: dockerconf, encoding: "Base64"
              }
            }
          }
          def output = sh(script: "skopeo inspect docker://${params.MBS_BACKEND_REPO}:${message.tag}", returnStdout: true).trim()
          def backendData = readJSON text: output
          env.BACKEND_IMAGE_REF = "${params.MBS_BACKEND_REPO}@${backendData.Digest}"
          echo "Current mbs-backend image is: ${env.BACKEND_IMAGE_REF}"
          echo "Triggering a job to test if ${env.FRONTEND_IMAGE_REF} and ${env.BACKEND_IMAGE_REF} meet all criteria of desired tag"
          env.C3IAAS_PROJECT = params.C3IAAS_REQUEST_PROJECT_BUILD_CONFIG_NAMESPACE
          env.IMAGE_IS_SCRATCH = false
          env.PIPELINE_ID = "c3i-mbs-tag-${message.tag}-${message.digest[-9..-1]}"
        }
      }
    }
    {% include "snippets/mbs-integration-test.groovy" %}
  }
}
{% include "snippets/functions.groovy" %}
