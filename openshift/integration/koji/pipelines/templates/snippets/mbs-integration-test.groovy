stage('Run integration tests') {
  stages {
    stage('Deploy test environment') {
      steps {
        script {
          {% include "snippets/get_paas_domain.groovy" %}
          if (!env.PIPELINE_ID) {
            env.PIPELINE_ID = "c3i-mbs-${UUID.randomUUID().toString().take(8)}"
          }
          openshift.withCluster() {
            openshift.withProject(params.PIPELINE_AS_A_SERVICE_BUILD_NAMESPACE) {
              c3i.buildAndWait(script: this, objs: "bc/pipeline-as-a-service",
                '-e', "DEFAULT_IMAGE_TAG=${env.ENVIRONMENT}",
                '-e', "PIPELINE_ID=${env.PIPELINE_ID}",
                '-e', "WAIVERDB_IMAGE=",
                '-e', "C3IAAS_PROJECT=${env.C3IAAS_PROJECT ?: ''}",
                '-e', "RESULTSDB_IMAGE=",
                '-e', "RESULTSDB_UPDATER_IMAGE=",
                '-e', "GREENWAVE_IMAGE=",
                '-e', "DATAGREPPER_IMAGE=",
                '-e', "DATANOMMER_IMAGE=",
                '-e', "MBS_BACKEND_IMAGE=${env.BACKEND_IMAGE_REF}",
                '-e', "MBS_FRONTEND_IMAGE=${env.FRONTEND_IMAGE_REF}",
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
          script {
            [env.BACKEND_IMAGE_REF, env.FRONTEND_IMAGE_REF].each {
              sendToResultsDB(it, 'passed')
            }
          }
        }
        failure {
          echo "Testcase ${env.CURRENT_TESTCASE} FAILED"
        }
      }
    }
  }
  post {
    failure {
      script {
        [env.BACKEND_IMAGE_REF, env.FRONTEND_IMAGE_REF].each {
          sendToResultsDB(it, 'failed')
        }
        openshift.withCluster() {
          openshift.withProject(env.PIPELINE_ID) {
            echo 'Getting logs from all deployments...'
            openshift.selector('pods', ['c3i.redhat.com/pipeline': env.PIPELINE_ID]).logs('--tail 100')
          }
        }
      }
    }
    cleanup {
      script {
        if (params.CLEANUP == 'true' && params.USE_C3IAAS != 'true') {
          openshift.withCluster() {
            openshift.withProject(env.PIPELINE_ID) {
              /* Tear down everything we just created */
              echo 'Tearing down test resources...'
              openshift.selector('all,pvc,configmap,secret',
                                 ['c3i.redhat.com/pipeline': env.PIPELINE_ID]).delete('--ignore-not-found=true')
            }
          }
        } else {
          echo 'Skipping cleanup'
        }
      }
    }
  }
}
