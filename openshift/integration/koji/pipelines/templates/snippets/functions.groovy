def sendToResultsDB(imageRef, status) {
  if (!params.MESSAGING_PROVIDER) {
    echo "Message bus is not set. Skipping send of:\nimageRef: ${imageRef}\nstatus: ${status}"
    return
  }
  def (repourl, digest) = imageRef.tokenize('@')
  def (registry, reponame) = repourl.split('/', 2)
  def image = reponame.split('/').last()
  def sendResult = sendCIMessage \
    providerName: params.MESSAGING_PROVIDER, \
    overrides: [topic: 'VirtualTopic.eng.ci.container-image.test.complete'], \
    messageType: 'Custom', \
    messageProperties: '', \
    messageContent: """
    {
      "ci": {
        "name": "C3I Jenkins",
        "team": "DevOps",
        "url": "${env.JENKINS_URL}",
        "docs": "https://pagure.io/fm-orchestrator/blob/master/f/openshift/integration/koji",
        "irc": "#pnt-devops-dev",
        "email": "pnt-factory2-devel@redhat.com",
        "environment": "${params.ENVIRONMENT}"
      },
      "run": {
        "url": "${env.BUILD_URL}",
        "log": "${env.BUILD_URL}/console",
        "debug": "",
        "rebuild": "${env.BUILD_URL}/rebuild/parametrized"
      },
      "artifact": {
        "type": "container-image",
        "repository": "${reponame}",
        "digest": "${digest}",
        "nvr": "${imageRef}",
        "issuer": "c3i-jenkins",
        "scratch": ${env.IMAGE_IS_SCRATCH},
        "id": "${image}@${digest}"
      },
      "system":
         [{
            "os": "${params.JENKINS_AGENT_IMAGE}",
            "provider": "openshift",
            "architecture": "x86_64"
         }],
      "type": "integration",
      "category": "${params.ENVIRONMENT}",
      "status": "${status}",
      "xunit": "",
      "generated_at": "${new Date().format("yyyy-MM-dd'T'HH:mm:ss'Z'", TimeZone.getTimeZone('UTC'))}",
      "namespace": "c3i",
      "version": "0.1.0"
    }
    """
  if (sendResult.getMessageId()) {
    // echo sent message id and content
    echo 'Successfully sent the test result to ResultsDB.'
    echo "Message ID: ${sendResult.getMessageId()}"
    echo "Message content: ${sendResult.getMessageContent()}"
  } else {
    echo 'Failed to sent the test result to ResultsDB.'
  }
}

