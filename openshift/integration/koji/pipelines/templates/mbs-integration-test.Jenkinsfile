library identifier: 'c3i@master', changelog: false,
  retriever: modernSCM([$class: "GitSCMSource", remote: "https://pagure.io/c3i-library.git"])
pipeline {
  agent {
    kubernetes {
      cloud params.JENKINS_AGENT_CLOUD_NAME
      label "jenkins-slave-${UUID.randomUUID().toString()}"
      serviceAccount params.JENKINS_AGENT_SERVICE_ACCOUNT
      defaultContainer 'jnlp'
      yaml """
      apiVersion: v1
      kind: Pod
      metadata:
        labels:
          app: "jenkins-${env.JOB_BASE_NAME.take(50)}"
          factory2-pipeline-kind: "mbs-integration-test-pipeline"
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
                key: ".dockerconfigjson"
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
    timeout(time: 60, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '10'))
  }
  environment {
    // Jenkins BUILD_TAG could be too long (> 63 characters) for OpenShift to consume
    TEST_ID = "${params.TEST_ID ?: 'jenkins-' + currentBuild.id + '-' + UUID.randomUUID().toString().substring(0,7)}"
  }
  stages {
    stage('Prepare') {
      steps {
        script {
          // Don't set ENVIRONMENT_LABEL in the environment block! Otherwise you will get 2 different UUIDs.
          env.ENVIRONMENT_LABEL = "test-${env.TEST_ID}"
        }
      }
    }
    stage('Call cleanup routine') {
      steps {
        script {
          // Cleanup all test environments that were created 1 hour ago in case of failures of previous cleanups.
          c3i.cleanup('umb', 'koji', 'mbs')
        }
      }
      post {
        failure {
          echo "Cleanup of old environments FAILED"
        }
      }
    }
    stage('Call UMB deployer') {
      steps {
        script {
          def keystore = ca.get_keystore("umb-${TEST_ID}-broker", 'mbskeys')
          def truststore = ca.get_truststore('mbstrust')
          umb.deploy(env.TEST_ID, keystore, 'mbskeys', truststore, 'mbstrust',
                     params.UMB_IMAGE)
        }
      }
      post {
        failure {
          echo "UMB deployment FAILED"
        }
      }
    }
    stage('Call Koji deployer') {
      steps {
        script {
          koji.deploy(env.TEST_ID, ca.get_ca_cert(),
                      ca.get_ssl_cert("koji-${TEST_ID}-hub"),
                      "amqps://umb-${TEST_ID}-broker",
                      ca.get_ssl_cert("koji-${TEST_ID}-msg"),
                      "mbs-${TEST_ID}-koji-admin",
                      params.KOJI_IMAGE)
        }
      }
      post {
        failure {
          echo "Koji deployment FAILED"
        }
      }
    }
    stage('Call MBS deployer') {
      steps {
        script {
          // Required for accessing src.fedoraproject.org
          def digicertca = readFile file: 'openshift/integration/koji/resources/certs/DigiCertHighAssuranceEVRootCA.pem'
          def cabundle = ca.get_ca_cert().cert + digicertca
          def msgcert = ca.get_ssl_cert("mbs-${TEST_ID}-msg")
          def frontendcert = ca.get_ssl_cert("mbs-${TEST_ID}-frontend")
          def kojicert = ca.get_ssl_cert("mbs-${TEST_ID}-koji-admin")
          mbs.deploy(env.TEST_ID, kojicert, ca.get_ca_cert(), msgcert, frontendcert, ca.get_ca_cert(), cabundle,
                     "https://koji-${TEST_ID}-hub",
                     "umb-${TEST_ID}-broker:61612",
                     params.MBS_BACKEND_IMAGE, params.MBS_FRONTEND_IMAGE)
        }
      }
      post {
        failure {
          echo "MBS deployment FAILED"
        }
      }
    }
    stage('Run tests') {
      steps {
        script {
          def testcases
          if (params.TESTCASES) {
            if (params.TESTCASES == 'skip') {
              testcases = []
              echo 'Skipping integration tests'
            } else {
              testcases = params.TESTCASES.split()
              echo "Using specified list of testcases: ${testcases}"
            }
          } else {
            testcases = findFiles(glob: 'openshift/integration/koji/pipelines/tests/*.groovy').collect {
              it.name.minus('.groovy')
            }
            echo "Using all available testcases: ${testcases}"
          }
          testcases.each { testcase ->
            env.CURRENT_TESTCASE = testcase
            echo "Running testcase ${testcase}..."
            def test = load "openshift/integration/koji/pipelines/tests/${testcase}.groovy"
            test.runTests()
          }
          echo "Tests complete"
        }
      }
      post {
        failure {
          echo "Testcase ${env.CURRENT_TESTCASE} FAILED"
        }
      }
    }
  }
  post {
    success {
      script {
        params.TEST_IMAGES.split().each {
          sendToResultsDB(it, 'passed')
        }
      }
    }
    failure {
      script {
        params.TEST_IMAGES.split().each {
          sendToResultsDB(it, 'failed')
        }
        openshift.withCluster() {
          echo 'Getting logs from all deployments...'
          def sel = openshift.selector('dc', ['environment': env.ENVIRONMENT_LABEL])
          sel.logs('--tail=100')
        }
      }
    }
    cleanup {
      script {
        if (params.CLEANUP == 'true') {
          openshift.withCluster() {
            /* Tear down everything we just created */
            echo 'Tearing down test resources...'
            openshift.selector('all,pvc,configmap,secret',
                               ['environment': env.ENVIRONMENT_LABEL]).delete('--ignore-not-found=true')
          }
        }
      }
    }
  }
}
def sendToResultsDB(imageRef, status) {
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
        "scratch": ${params.IMAGE_IS_SCRATCH},
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
