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
    skipDefaultCheckout()
  }
  environment {
    PIPELINE_ID = "${params.TEST_NAMESPACE}"
  }
  stages {
    stage('Prepare') {
      steps {
        script {
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
              c3i.cleanup(script: this, 'krb5', 'umb', 'koji', 'mbs')
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
      when {
         expression { !env.PAAS_DOMAIN }
      }
      steps {
        script {
          openshift.withCluster() {
            openshift.withProject(env.PIPELINE_ID) {
              def testroute = openshift.create('route', 'edge', 'test',  '--service=test', '--port=8080')
              def testhost = testroute.object().spec.host
              env.PAAS_DOMAIN = testhost.minus("test-${env.PIPELINE_ID}.")
              testroute.delete()
            }
          }
        }
      }
      post {
        success {
          echo "Routes end with ${env.PAAS_DOMAIN}"
        }
      }
    }
    stage('Deploy test environment') {
      steps {
        script {
          openshift.withCluster() {
            openshift.withProject(params.PIPELINE_AS_A_SERVICE_BUILD_NAMESPACE) {
              c3i.buildAndWait(script: this, objs: "bc/pipeline-as-a-service",
                '-e', "DEFAULT_IMAGE_TAG=${env.ENVIRONMENT}",
                '-e', "PIPELINE_ID=${env.PIPELINE_ID}",
                '-e', "WAIVERDB_IMAGE=",
                '-e', "C3IAAS_PROJECT=",
                '-e', "RESULTSDB_IMAGE=",
                '-e', "RESULTSDB_UPDATER_IMAGE=",
                '-e', "GREENWAVE_IMAGE=",
                '-e', "DATAGREPPER_IMAGE=",
                '-e', "DATANOMMER_IMAGE=",
                '-e', "MBS_BACKEND_IMAGE=${env.MBS_BACKEND_IMAGE}",
                '-e', "MBS_FRONTEND_IMAGE=${env.MBS_FRONTEND_IMAGE}",
                '-e', "PAAS_DOMAIN=${env.PAAS_DOMAIN}"
              )
            }
          }
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
            echo 'Getting logs from all deployments...'
            openshift.selector('pods', ['c3i.redhat.com/pipeline': env.PIPELINE_ID]).logs('--tail 100')
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
                               ['c3i.redhat.com/pipeline': env.PIPELINE_ID]).delete('--ignore-not-found=true')
          }
        } else {
          echo 'Skipping cleanup'
        }
      }
    }
  }
}
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
