// Use scripted syntax because CIBuildTrigger currently doesn't support the declarative syntax
properties([
  disableConcurrentBuilds(),
  pipelineTriggers([
    // example: https://github.com/jenkinsci/jms-messaging-plugin/blob/9b9387c3a52f037ba0d019c2ebcf2a2796fc6397/src/test/java/com/redhat/jenkins/plugins/ci/integration/AmqMessagingPluginIntegrationTest.java
    [$class: 'CIBuildTrigger',
      providerData: [$class: 'ActiveMQSubscriberProviderData',
        name: params.MESSAGING_PROVIDER,
        overrides: [topic: params.MESSAGING_TOPIC],
        selector: "repo = '${params.TRACKED_CONTAINER_REPO}' AND action IN ('added', 'updated') AND tag = '${params.TRACKED_TAG}'",
      ],
    ],
  ]),
])

if (!params.CI_MESSAGE) {
  echo 'This build is not started by a CI message. Only configurations were done.'
  return
}

def label = "jenkins-slave-${UUID.randomUUID().toString()}"
podTemplate(
  cloud: "${params.JENKINS_AGENT_CLOUD_NAME}",
  label: label,
  serviceAccount: "${env.JENKINS_AGENT_SERVICE_ACCOUNT}",
  defaultContainer: 'jnlp',
  yaml: """
    apiVersion: v1
    kind: Pod
    metadata:
      labels:
        app: "jenkins-${env.JOB_BASE_NAME.take(50)}"
        factory2-pipeline-kind: "mbs-repotracker-trigger"
        factory2-pipeline-build-number: "${env.BUILD_NUMBER}"
    spec:
      containers:
      - name: jnlp
        image: ${params.JENKINS_AGENT_IMAGE}
        imagePullPolicy: Always
        tty: true
        env:
        - name: REGISTRY_CREDENTIALS
          valueFrom:
            secretKeyRef:
              name: "${params.CONTAINER_REGISTRY_CREDENTIALS}"
              key: ".dockerconfigjson"
        resources:
          requests:
            memory: 256Mi
            cpu: 200m
          limits:
            memory: 512Mi
            cpu: 300m
    """
) {
  node(label) {
    stage('Trigger tests') {
      def message = readJSON text: params.CI_MESSAGE
      echo "Tag :${message.tag} is ${message.action} in ${message.repo}. New digest: ${message.digest}"
      def frontendImage = "${message.repo}@${message.digest}"
      // We have the digest of the current frontend image with this tag.
      // Lookup the digest of the current backend image with the same tag.
      if (env.REGISTRY_CREDENTIALS) {
        dir ("${env.HOME}/.docker") {
          writeFile file: 'config.json', text: env.REGISTRY_CREDENTIALS
        }
      }
      def output = sh(script: "skopeo inspect docker://${params.MBS_BACKEND_REPO}:${message.tag}", returnStdout: true).trim()
      def backendData = readJSON text: output
      def backendImage = "${params.MBS_BACKEND_REPO}@${backendData.Digest}"
      echo "Current mbs-backend image is: ${backendImage}"
      echo "Triggering a job to test if ${frontendImage} and ${backendImage} meet all criteria of desired tag"
      openshift.withCluster() {
        openshift.withProject(params.TEST_JOB_NAMESPACE) {
          def testBcSelector = openshift.selector('bc', params.TEST_JOB_NAME)
          def buildSelector = testBcSelector.startBuild(
            '-e', "MBS_BACKEND_IMAGE=${backendImage}",
            '-e', "MBS_FRONTEND_IMAGE=${frontendImage}",
            '-e', "TEST_IMAGES='${backendImage} ${frontendImage}'",
            '-e', "IMAGE_IS_SCRATCH=false"
          )
          buildSelector.watch {
            return !(it.object().status.phase in ["New", "Pending"])
          }
          buildInfo = buildSelector.object()
          echo "Build ${buildInfo.metadata.annotations['openshift.io/jenkins-build-uri'] ?: buildInfo.metadata.name} started."
        }
      }
    }
  }
}
