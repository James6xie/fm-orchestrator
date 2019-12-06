{% include "snippets/c3i-library.groovy" %}
pipeline {
  {% include "snippets/default-agent.groovy" %}
  options {
    timestamps()
    timeout(time: 60, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '10'))
  }
  environment {
    PIPELINE_NAMESPACE = readFile('/run/secrets/kubernetes.io/serviceaccount/namespace').trim()
    PAGURE_URL = "${PAGURE_URL}"
    PAGURE_API = "${env.PAGURE_URL}/api/0"
    PAGURE_REPO_NAME = "${PAGURE_REPO_NAME}"
    PAGURE_REPO_IS_FORK = "${PAGURE_REPO_IS_FORK}"
    PAGURE_POLLING_FOR_PR = "${PAGURE_POLLING_FOR_PR}"
    PAGURE_REPO_HOME = "${env.PAGURE_URL}${env.PAGURE_REPO_IS_FORK == 'true' ? '/fork' : ''}/${env.PAGURE_REPO_NAME}"
    GIT_URL = "${env.PAGURE_URL}/${env.PAGURE_REPO_IS_FORK == 'true' ? 'forks/' : ''}${env.PAGURE_REPO_NAME}.git"
    PREMERGE_JOB_NAME = "${PREMERGE_JOB_NAME}"
    POSTMERGE_JOB_NAME = "${POSTMERGE_JOB_NAME}"
  }
  triggers { pollSCM("${PAGURE_POLLING_SCHEDULE}") }
  stages {
    stage('Prepare') {
      agent { label 'master' }
      steps {
        script {
          def polled = env.PAGURE_POLLING_FOR_PR == 'true' ? 'pull/*/head' : "${PAGURE_POLLED_BRANCH}"
          // Need to prefix the rev with origin/ for pollSCM to work correctly
          def rev = "origin/${polled}"
          def scmVars = c3i.clone(repo: env.GIT_URL, branch: polled, rev: rev)
          env.GIT_COMMIT = scmVars.GIT_COMMIT
          // setting build display name
          def prefix = 'origin/'
          def branch = scmVars.GIT_BRANCH.startsWith(prefix) ? scmVars.GIT_BRANCH.substring(prefix.size())
            : scmVars.GIT_BRANCH // origin/pull/1234/head -> pull/1234/head, origin/master -> master
          env.MBS_GIT_BRANCH = branch
          echo "Build on branch=${env.MBS_GIT_BRANCH}, commit=${env.GIT_COMMIT}"
          if (env.PAGURE_POLLING_FOR_PR == 'false') {
            currentBuild.displayName = "${env.MBS_GIT_BRANCH}: ${env.GIT_COMMIT.substring(0, 7)}"
            currentBuild.description = """<a href="${env.PAGURE_REPO_HOME}/c/${env.GIT_COMMIT}">${currentBuild.displayName}</a>"""
          } else if (env.PAGURE_POLLING_FOR_PR == 'true' && branch ==~ /^pull\/[0-9]+\/head$/) {
            env.PR_NO = branch.split('/')[1]
            def prInfo = pagure.getPR(env.PR_NO)
            if (prInfo.status == 'Open') {
              env.PR_URL = "${env.PAGURE_REPO_HOME}/pull-request/${env.PR_NO}"
              // To HTML syntax in build description, go to `Jenkins/Global Security/Markup Formatter` and select 'Safe HTML'.
              def pagureLink = """<a href="${env.PR_URL}">PR#${env.PR_NO}</a>"""
              echo "Building PR #${env.PR_NO}: ${env.PR_URL}"
              currentBuild.displayName = "PR#${env.PR_NO}"
              currentBuild.description = pagureLink
            } else {
              echo "Skipping PR#${env.PR_NO} because it is ${prInfo.status}"
              env.SKIP = 'true'
            }
          } else { // This shouldn't happen.
            error("Build is aborted due to unexpected polling trigger actions.")
          }
        }
      }
    }
    stage('Update pipeline jobs') {
      when {
        expression {
          return "${PIPELINE_UPDATE_JOBS_DIR}" && env.PAGURE_POLLING_FOR_PR == 'false' && env.MBS_GIT_BRANCH == "${PAGURE_POLLED_BRANCH}"
        }
      }
      steps {
        script {
          c3i.clone(repo: env.GIT_URL, branch: env.MBS_GIT_BRANCH)
          dir('openshift/integration/koji/pipelines') {
            sh '''
            make install JOBS_DIR="${PIPELINE_UPDATE_JOBS_DIR}"
            '''
          }
        }
      }
    }
    stage('Build') {
      when {
        not {
          environment name: 'SKIP', value: 'true'
        }
      }
      steps {
        script {
          openshift.withCluster() {
            echo 'Starting a MBS build run...'
            def devBuild = c3i.build(script: this,
              objs: "bc/${env.PAGURE_POLLING_FOR_PR == 'true' ? env.PREMERGE_JOB_NAME : env.POSTMERGE_JOB_NAME}",
              '-e', "MBS_GIT_REF=${env.MBS_GIT_BRANCH}", '-e', "PAGURE_REPO_IS_FORK=${env.PAGURE_REPO_IS_FORK}",
              '-e', "PAGURE_REPO_NAME=${env.PAGURE_REPO_NAME}"
            )
            c3i.waitForBuildStart(script: this, build: devBuild)
            def devBuildInfo = devBuild.object()
            def downstreamBuildName = devBuildInfo.metadata.name
            def downstreamBuildUrl = devBuildInfo.metadata.annotations['openshift.io/jenkins-build-uri']
            echo "Downstream build ${downstreamBuildName}(${downstreamBuildUrl}) started."
          }
        }
      }
    }
  }
}
