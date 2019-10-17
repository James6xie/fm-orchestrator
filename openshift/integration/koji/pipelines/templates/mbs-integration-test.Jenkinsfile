library identifier: 'c3i@master', changelog: false,
  retriever: modernSCM([$class: 'GitSCMSource', remote: 'https://pagure.io/c3i-library.git'])
def deployments
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
    disableConcurrentBuilds()
    skipDefaultCheckout()
  }
  environment {
    // Jenkins BUILD_TAG could be too long (> 63 characters) for OpenShift to consume
    TEST_ID = "${params.TEST_ID ?: UUID.randomUUID().toString().substring(0,7)}"
  }
  stages {
    stage('Prepare') {
      steps {
        script {
          // Don't set ENVIRONMENT_LABEL in the environment block! Otherwise you will get 2 different UUIDs.
          env.ENVIRONMENT_LABEL = "test-${env.TEST_ID}"
          // MBS_GIT_REF can be either a regular branch (in the heads/ namespace), a pull request
          // branch (in the pull/ namespace), or a full 40-character sha1, which is assumed to
          // exist on the master branch.
          def branch = params.MBS_GIT_REF ==~ '[0-9a-f]{40}' ? 'master' : params.MBS_GIT_REF
          c3i.clone(repo: params.MBS_GIT_REPO, branch: branch, rev: params.MBS_GIT_REF)
          // get current commit ID
          // FIXME: Due to a bug discribed in https://issues.jenkins-ci.org/browse/JENKINS-45489,
          // the return value of checkout() is unreliable.
          // Not working: env.MBS_GIT_COMMIT = scmVars.GIT_COMMIT
          env.MBS_GIT_COMMIT = sh(returnStdout: true, script: 'git rev-parse HEAD').trim()
          echo "Running integration tests for ${branch}, commit=${env.MBS_GIT_COMMIT}"
          currentBuild.displayName = "${branch}: ${env.MBS_GIT_COMMIT.take(7)}"
        }
      }
    }
    stage('Cleanup') {
      when {
        expression {
          // Only run cleanup if we're running tests in the default namespace.
          return !params.TEST_NAMESPACE
        }
      }
      steps {
        script {
          openshift.withCluster() {
            openshift.withProject() {
              // Cleanup all test environments that were created 1 hour ago in case of failures of previous cleanups.
              c3i.cleanup(script: this, 'umb', 'koji', 'mbs')
            }
          }
        }
      }
      post {
        failure {
          echo "Cleanup of old environments FAILED"
        }
      }
    }
    stage('Route suffix') {
      steps {
        script {
          openshift.withCluster() {
            openshift.withProject(params.TEST_NAMESPACE) {
              def testroute = openshift.create('route', 'edge', 'test',  '--service=test', '--port=8080')
              def testhost = testroute.object().spec.host
              // trim off the test- prefix
              env.ROUTE_SUFFIX = testhost.drop(5)
              testroute.delete()
            }
          }
        }
      }
      post {
        success {
          echo "Routes end with ${env.ROUTE_SUFFIX}"
        }
      }
    }
    stage('Generate CA') {
      steps {
        script {
          ca.gen_ca()
        }
      }
    }
    stage('Deploy UMB') {
      steps {
        script {
          openshift.withCluster() {
            openshift.withProject(params.TEST_NAMESPACE) {
              // The extact hostname doesn't matter, (as long as it resolves to the cluster) because traffic will
              // be routed to the pod via the NodePort.
              // However, the hostname we use to access the service must be a subjectAltName of the certificate
              // being served by the service.
              env.UMB_HOST = "umb-${TEST_ID}-${env.ROUTE_SUFFIX}"
              ca.gen_ssl_cert("umb-${TEST_ID}-broker", env.UMB_HOST)
              def keystore = ca.get_keystore("umb-${TEST_ID}-broker", 'mbskeys')
              def truststore = ca.get_truststore('mbstrust')
              deployments = umb.deploy(script: this, test_id: env.TEST_ID,
                                       keystore_data: keystore, keystore_password: 'mbskeys',
                                       truststore_data: truststore, truststore_password: 'mbstrust',
                                       broker_image: params.UMB_IMAGE)
              def ports = openshift.selector('service', "umb-${TEST_ID}-broker").object().spec.ports
              env.UMB_AMQPS_PORT = ports.find { it.name == 'amqps' }.nodePort
              env.UMB_STOMP_SSL_PORT = ports.find { it.name == 'stomp-ssl' }.nodePort
            }
          }
        }
      }
      post {
        success {
          echo "UMB deployed: amqps: ${env.UMB_HOST}:${env.UMB_AMQPS_PORT} stomp-ssl: ${env.UMB_HOST}:${env.UMB_STOMP_SSL_PORT}"
        }
        failure {
          echo "UMB deployment FAILED"
        }
      }
    }
    stage('Deploy Koji') {
      steps {
        script {
          openshift.withCluster() {
            openshift.withProject(params.TEST_NAMESPACE) {
              env.KOJI_SSL_HOST = "koji-${TEST_ID}-hub-${env.ROUTE_SUFFIX}"
              def hubcert = ca.get_ssl_cert("koji-${TEST_ID}-hub", env.KOJI_SSL_HOST)
              env.KOJI_ADMIN = "mbs-${TEST_ID}-koji-admin"
              env.KOJI_MSG_CERT = "koji-${TEST_ID}-msg"
              def deployed = koji.deploy(script: this, test_id: env.TEST_ID,
                                         hubca: ca.get_ca_cert(), hubcert: hubcert,
                                         brokerurl: "amqps://${env.UMB_HOST}:${env.UMB_AMQPS_PORT}",
                                         brokercert: ca.get_ssl_cert(env.KOJI_MSG_CERT),
                                         admin_user: env.KOJI_ADMIN,
                                         hub_image: params.KOJI_IMAGE)
              deployments = deployments.union(deployed)
            }
          }
        }
      }
      post {
        success {
          echo "Koji deployed: hub: https://${env.KOJI_SSL_HOST}/"
        }
        failure {
          echo "Koji deployment FAILED"
        }
      }
    }
    stage('Deploy MBS') {
      steps {
        script {
          env.MBS_SSL_HOST = "mbs-${TEST_ID}-frontend-${env.ROUTE_SUFFIX}"
          def frontendcert = ca.get_ssl_cert("mbs-${TEST_ID}-frontend", env.MBS_SSL_HOST)
          // Required for accessing src.fedoraproject.org
          def digicertca = readFile file: 'openshift/integration/koji/resources/certs/DigiCertHighAssuranceEVRootCA.pem'
          def cabundle = ca.get_ca_cert().cert + digicertca
          def msgcert = ca.get_ssl_cert("mbs-${TEST_ID}-msg")
          def kojicert = ca.get_ssl_cert(env.KOJI_ADMIN)
          openshift.withCluster() {
            openshift.withProject(params.TEST_NAMESPACE) {
              def deployed = mbs.deploy(script: this, test_id: env.TEST_ID,
                                        kojicert: kojicert, kojica: ca.get_ca_cert(),
                                        brokercert: msgcert,
                                        frontendcert: frontendcert, frontendca: ca.get_ca_cert(),
                                        cacerts: cabundle,
                                        kojiurl: "https://${env.KOJI_SSL_HOST}",
                                        stompuri: "${env.UMB_HOST}:${env.UMB_STOMP_SSL_PORT}",
                                        backend_image: params.MBS_BACKEND_IMAGE,
                                        frontend_image: params.MBS_FRONTEND_IMAGE)
              deployments = deployments.union(deployed)
            }
          }
        }
      }
      post {
        success {
          echo "MBS deployed: frontend: https://${env.MBS_SSL_HOST}/"
        }
        failure {
          echo "MBS deployment FAILED"
        }
      }
    }
    stage('Wait for deployments') {
      steps {
        script {
          openshift.withCluster() {
            openshift.withProject(params.TEST_NAMESPACE) {
              c3i.waitForDeployment(script: this, objs: deployments)
            }
          }
        }
      }
      post {
        success {
          echo "Deployments complete"
        }
        failure {
          echo 'Deployments FAILED'
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
        }
      }
      post {
        success {
          echo "All tests successful"
        }
        failure {
          echo "Testcase ${env.CURRENT_TESTCASE} FAILED"
        }
      }
    }
  }
  post {
    success {
      script {
        params.TEST_IMAGES.split(',').each {
          sendToResultsDB(it, 'passed')
        }
      }
    }
    failure {
      script {
        params.TEST_IMAGES.split(',').each {
          sendToResultsDB(it, 'failed')
        }
        openshift.withCluster() {
          openshift.withProject(params.TEST_NAMESPACE) {
            if (deployments) {
              echo 'Getting logs from all deployments...'
              deployments.logs('--tail=100')
            }
          }
        }
      }
    }
    cleanup {
      script {
        if (params.CLEANUP == 'true' && !params.TEST_NAMESPACE) {
          openshift.withCluster() {
            /* Tear down everything we just created */
            echo 'Tearing down test resources...'
            openshift.selector('all,pvc,configmap,secret',
                               ['environment': env.ENVIRONMENT_LABEL]).delete('--ignore-not-found=true')
          }
        } else {
          echo 'Skipping cleanup'
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
