pipeline {
  agent {
    kubernetes {
      cloud "${params.JENKINS_AGENT_CLOUD_NAME}"
      label "jenkins-slave-${UUID.randomUUID().toString()}"
      serviceAccount "${params.JENKINS_AGENT_SERVICE_ACCOUNT}"
      defaultContainer 'jnlp'
      yaml """
      apiVersion: v1
      kind: Pod
      metadata:
        labels:
          app: "jenkins-${env.JOB_BASE_NAME.take(50)}"
          factory2-pipeline-kind: "mbs-image-promotion-pipeline"
          factory2-pipeline-build-number: "${env.BUILD_NUMBER}"
      spec:
        containers:
        - name: jnlp
          image: "${params.JENKINS_AGENT_IMAGE}"
          imagePullPolicy: Always
          tty: true
          env:
          - name: REGISTRY_CREDENTIALS
            valueFrom:
              secretKeyRef:
                name: "${params.CONTAINER_REGISTRY_CREDENTIALS}"
                key: '.dockerconfigjson'
          resources:
            requests:
              memory: 512Mi
              cpu: 300m
            limits:
              memory: 768Mi
              cpu: 500m
      """
    }
  }
  options {
    timestamps()
    timeout(time: 30, unit: 'MINUTES')
  }
  environment {
    PIPELINE_NAMESPACE = readFile(file: '/run/secrets/kubernetes.io/serviceaccount/namespace').trim()
    SERVICE_ACCOUNT_TOKEN = readFile(file: '/run/secrets/kubernetes.io/serviceaccount/token').trim()
  }
  stages {
    stage ('Prepare') {
      steps {
        script {
          // Setting up registry credentials
          dir ("${env.HOME}/.docker") {
            // for the OpenShift internal registry
            def dockerConfig = readJSON text: '{ "auths": {} }'
            dockerConfig.auths['docker-registry.default.svc:5000'] = [
              'email': '',
              'auth': sh(returnStdout: true, script: 'set +x; echo -n "serviceaccount:$SERVICE_ACCOUNT_TOKEN" | base64 -').trim()
              ]
            // merging user specified credentials
            if (env.REGISTRY_CREDENTIALS) {
              toBeMerged = readJSON text: env.REGISTRY_CREDENTIALS
              dockerConfig.auths.putAll(toBeMerged.auths)
            }
            // writing to ~/.docker/config.json
            writeJSON file: 'config.json', json: dockerConfig
          }
        }
      }
    }
    stage('Pull image') {
      steps {
        echo "Pulling container image ${params.IMAGE}..."
        withEnv(["SOURCE_IMAGE_REF=${params.IMAGE}"]) {
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
                def dest = "${it}:${params.DEST_TAG}"
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
          def destRef = "${params.DEST_IMAGESTREAM_NAMESPACE ?: env.PIPELINE_NAMESPACE}/${params.DEST_IMAGESTREAM_NAME}:${params.DEST_TAG}"
          openshift.withCluster() {
            echo "Tagging ${params.IMAGE} into ${destRef}..."
            openshift.tag('--source=docker', params.IMAGE, destRef)
          }
        }
      }
    }
  }
}
