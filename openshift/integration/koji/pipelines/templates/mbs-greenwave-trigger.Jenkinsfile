// Use scripted syntax because CIBuildTrigger currently doesn't support the declarative syntax
properties([
  buildDiscarder(logRotator(numToKeepStr: '10')),
  disableConcurrentBuilds(),
  pipelineTriggers([
    // example: https://github.com/jenkinsci/jms-messaging-plugin/blob/9b9387c3a52f037ba0d019c2ebcf2a2796fc6397/src/test/java/com/redhat/jenkins/plugins/ci/integration/AmqMessagingPluginIntegrationTest.java
    [$class: 'CIBuildTrigger',
      providerData: [$class: 'ActiveMQSubscriberProviderData',
        name: params.MESSAGING_PROVIDER,
        overrides: [topic: params.MESSAGING_TOPIC],
        checks: [
          [field: '$.msg.subject_type', expectedValue: 'container-image'],
          [field: '$.msg.subject_identifier', expectedValue: params.SUBJECT_IDENTIFIER_REGEX],
          [field: '$.msg.decision_context', expectedValue: params.DECISION_CONTEXT_REGEX],
          [field: '$.msg.policies_satisfied', expectedValue: 'true'],
        ],
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
  serviceAccount: "${params.JENKINS_AGENT_SERVICE_ACCOUNT}",
  defaultContainer: 'jnlp',
  yaml: """
    apiVersion: v1
    kind: Pod
    metadata:
      labels:
        app: "jenkins-${env.JOB_BASE_NAME.take(50)}"
        factory2-pipeline-kind: "mbs-greenwave-trigger"
        factory2-pipeline-build-number: "${env.BUILD_NUMBER}"
    spec:
      containers:
      - name: jnlp
        image: ${params.JENKINS_AGENT_IMAGE}
        imagePullPolicy: Always
        tty: true
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
    stage('Trigger promotion') {
      def message = readJSON text: params.CI_MESSAGE
      // Extract the digest of the image to be promoted.
      // e.g. factory2/waiverdb@sha256:35201c572fc8a137862b7a256476add8d7465fa5043d53d117f4132402f8ef6b
      //   -> sha256:35201c572fc8a137862b7a256476add8d7465fa5043d53d117f4132402f8ef6b
      def digest = (message.msg.subject_identifier =~ /@(sha256:\w+)$/)[0][1]
      // Generate the pull spec of the image
      // e.g. quay.io/factory2/waiverdb@sha256:35201c572fc8a137862b7a256476add8d7465fa5043d53d117f4132402f8ef6b
      def image = "${params.SOURCE_CONTAINER_REPO}@${digest}"
      echo "Starting a new build to promote image ${image} to :${params.TARGET_TAG}..."
      openshift.withCluster() {
        def bcSelector = openshift.selector('bc', params.IMAGE_PROMOTION_JOB)
        def buildSelector = bcSelector.startBuild(
            '-e', "IMAGE=${image}",
            '-e', "DEST_TAG=${params.TARGET_TAG}",
          )
          bcSelector.watch {
            return !(it.object().status.phase in ["New", "Pending"])
          }
          buildInfo = buildSelector.object()
          echo "Build ${buildInfo.metadata.annotations['openshift.io/jenkins-build-uri'] ?: buildInfo.metadata.name} started."
      }
    }
  }
}
