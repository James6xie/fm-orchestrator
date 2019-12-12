{% include "snippets/c3i-library.groovy" %}
pipeline {
  {% include "snippets/default-agent.groovy" %}
  options {
    timestamps()
    timeout(time: 30, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '10'))
  }
  environment {
    PIPELINE_NAMESPACE = readFile(file: '/run/secrets/kubernetes.io/serviceaccount/namespace').trim()
    SERVICE_ACCOUNT_TOKEN = readFile(file: '/run/secrets/kubernetes.io/serviceaccount/token').trim()
  }
  triggers {
    ciBuildTrigger(
      noSquash: false,
      providerList: [
        activeMQSubscriber(
          name: params.MESSAGING_PROVIDER,
          overrides: [topic: params.MESSAGING_TOPIC],
          checks: [
            [field: '$.msg.subject_type', expectedValue: 'container-image'],
            [field: '$.msg.subject_identifier', expectedValue: params.SUBJECT_IDENTIFIER_REGEX],
            [field: '$.msg.decision_context', expectedValue: params.DECISION_CONTEXT_REGEX],
            [field: '$.msg.policies_satisfied', expectedValue: 'true'],
          ]
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
          def message = readJSON text: params.CI_MESSAGE
          // Extract the digest of the image to be promoted.
          // e.g. factory2/waiverdb@sha256:35201c572fc8a137862b7a256476add8d7465fa5043d53d117f4132402f8ef6b
          //   -> sha256:35201c572fc8a137862b7a256476add8d7465fa5043d53d117f4132402f8ef6b
          def digest = (message.msg.subject_identifier =~ /@(sha256:\w+)$/)[0][1]
          // Generate the pull spec of the image
          // e.g. quay.io/mkovarik/waiverdb@sha256:35201c572fc8a137862b7a256476add8d7465fa5043d53d117f4132402f8ef6b
          env.IMAGE = "${params.SOURCE_CONTAINER_REPO}@${digest}"
          echo "Starting promotion of image ${env.IMAGE} to :${params.TARGET_TAG}..."
          // Setting up registry credentials
          dir ("${env.HOME}/.docker") {
            // for the OpenShift internal registry
            def dockerConfig = readJSON text: '{ "auths": {} }'
            dockerConfig.auths['docker-registry.default.svc:5000'] = [
              'email': '',
              'auth': sh(returnStdout: true, script: 'set +x; echo -n "serviceaccount:$SERVICE_ACCOUNT_TOKEN" | base64 -').trim()
              ]
            // merging user specified credentials
            if (params.CONTAINER_REGISTRY_CREDENTIALS) {
              openshift.withCluster() {
                def dockerconf = openshift.selector('secret', params.CONTAINER_REGISTRY_CREDENTIALS).object().data['.dockerconfigjson']
                def dockerString = new String(dockerconf.decodeBase64())
                toBeMerged = readJSON text: dockerString
                dockerConfig.auths.putAll(toBeMerged.auths)
              }
            }
            // writing to ~/.docker/config.json
            writeJSON file: 'config.json', json: dockerConfig
          }
        }
      }
    }
    stage('Pull image') {
      steps {
        echo "Pulling container image ${env.IMAGE}..."
        withEnv(["SOURCE_IMAGE_REF=${env.IMAGE}"]) {
          sh '''
            set -e +x # hide the token from Jenkins console
            mkdir -p _image
            skopeo copy docker://"$SOURCE_IMAGE_REF" dir:_image
          '''
        }
      }
    }
    stage('Promote image') {
      steps {
        script {
          def destinations = params.PROMOTING_DESTINATIONS ? params.PROMOTING_DESTINATIONS.split(',') : []
          openshift.withCluster() {
            def pushTasks = destinations.collectEntries {
              ["Pushing ${it}" : {
                def dest = "${it}:${params.TARGET_TAG}"
                // Only docker and atomic registries are allowed
                if (!dest.startsWith('atomic:') && !dest.startsWith('docker://')) {
                  dest = "docker://${dest}"
                }
                echo "Pushing container image to ${dest}..."
                withEnv(["DEST_IMAGE_REF=${dest}"]) {
                  retry(5) {
                    sh 'skopeo copy dir:_image "$DEST_IMAGE_REF"'
                  }
                }
              }]
            }
            parallel pushTasks
          }
        }
      }
    }
    stage('Tag ImageStream') {
      when {
        expression {
          return params.DEST_IMAGESTREAM_NAME && params.TAG_INTO_IMAGESTREAM == "true"
        }
      }
      steps {
        script {
          def destRef = "${params.DEST_IMAGESTREAM_NAMESPACE ?: env.PIPELINE_NAMESPACE}/${params.DEST_IMAGESTREAM_NAME}:${params.TARGET_TAG}"
          openshift.withCluster() {
            echo "Tagging ${env.IMAGE} into ${destRef}..."
            openshift.tag('--source=docker', env.IMAGE, destRef)
          }
        }
      }
    }
  }
}
