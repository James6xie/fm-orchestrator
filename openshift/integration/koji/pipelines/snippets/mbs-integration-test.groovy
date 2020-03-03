stage('Get image refs') {
  when {
    expression { !env.FRONTEND_IMAGE_REF }
  }
  steps {
    script {
      env.FRONTEND_IMAGE_REF = env.IMAGE
      if (params.CONTAINER_REGISTRY_CREDENTIALS) {
        dir ("${env.HOME}/.docker") {
          openshift.withCluster() {
            def dockerconf = openshift.selector('secret', params.CONTAINER_REGISTRY_CREDENTIALS).object().data['.dockerconfigjson']
            writeFile file: 'config.json', text: dockerconf, encoding: "Base64"
          }
        }
        def output = sh(script: "skopeo inspect docker://${params.MBS_BACKEND_REPO}:${params.TRACKED_TAG}", returnStdout: true).trim()
        def backendData = readJSON text: output
        env.BACKEND_IMAGE_REF = "${params.MBS_BACKEND_REPO}@${backendData.Digest}"
      }
    }
  }
}
stage('Run integration tests') {
  stages {
    stage('Deploy test environment') {
      steps {
        script {
          if (!env.PIPELINE_ID) {
            env.PIPELINE_ID = "c3i-mbs-${UUID.randomUUID().toString().take(8)}"
          }
          openshift.withCluster() {
            openshift.withProject(params.PIPELINE_AS_A_SERVICE_BUILD_NAMESPACE) {
              def services = 'umb mbs-frontend mbs-backend krb5 ldap koji-hub'
              if (env.REUSE_PROJECT == "true") {
                c3i.buildAndWait(script: this, objs: "bc/pipeline-as-a-service",
                  '-e', "DEFAULT_IMAGE_TAG=${env.ENVIRONMENT}",
                  '-e', "PIPELINE_ID=${env.PIPELINE_ID}",
                  '-e', "TRIGGERED_BY=${env.BUILD_URL}",
                  '-e', "SERVICES_TO_DEPLOY='${services}'",
                  '-e', "MBS_BACKEND_IMAGE=${env.BACKEND_IMAGE_REF}",
                  '-e', "MBS_FRONTEND_IMAGE=${env.FRONTEND_IMAGE_REF}",
                  '-e', "PAAS_DOMAIN=${env.PAAS_DOMAIN}",
                  '-e', 'C3IAAS_PROJECT=""'
                )
              }
              else {
                c3i.buildAndWait(script: this, objs: "bc/pipeline-as-a-service",
                  '-e', "DEFAULT_IMAGE_TAG=${env.ENVIRONMENT}",
                  '-e', "PIPELINE_ID=${env.PIPELINE_ID}",
                  '-e', "TRIGGERED_BY=${env.BUILD_URL}",
                  '-e', "SERVICES_TO_DEPLOY='${services}'",
                  '-e', "MBS_BACKEND_IMAGE=${env.BACKEND_IMAGE_REF}",
                  '-e', "MBS_FRONTEND_IMAGE=${env.FRONTEND_IMAGE_REF}",
                  '-e', "PAAS_DOMAIN=${env.PAAS_DOMAIN}",
                )
              }
            }
          }
        }
      }
    }
    stage('Run tests') {
      steps {
        script {
          checkout([$class: 'GitSCM',
            branches: [[name: env.GIT_REPO_REF]],
            userRemoteConfigs: [[url: params.GIT_REPO, refspec: '+refs/heads/*:refs/remotes/origin/* +refs/pull/*/head:refs/remotes/origin/pull/*/head']],
          ])
          sh "openshift/integration/koji/pipelines/tests/runtests ${env.PIPELINE_ID}"
        }
      }
      post {
        success {
          echo "All tests successful"
        }
        failure {
          echo "Testcases FAILED"
        }
      }
    }
  }
  post {
    failure {
      script {
        openshift.withCluster() {
          openshift.withProject(env.PIPELINE_ID) {
            echo 'Getting logs from all deployments...'
            openshift.selector('pods', ['c3i.redhat.com/pipeline': env.PIPELINE_ID]).logs('--tail 100')
          }
        }
      }
    }
    always {
      script {
        pd = controller.getVars()
        [[pd.MBS_BACKEND_IMAGE, pd.MBS_BACKEND_IMAGE_DIGEST], [pd.MBS_FRONTEND_IMAGE, pd.MBS_FRONTEND_IMAGE_DIGEST]].each {
          c3i.sendResultToMessageBus(
            imageRef: it[0],
            digest: it[1],
            environment: env.ENVIRONMENT, 
            docs: 'https://pagure.io/fm-orchestrator/blob/master/f/openshift/integration/koji',
            scratch: env.IMAGE_IS_SCRATCH
          )
        }
      }
    }
  }
}
