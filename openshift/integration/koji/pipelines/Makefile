OC:=oc
OCFLAGS:=
JOBS_DIR:=jobs
TEMPLATES_DIR:=templates
JOB_PARAM_FILES:=$(wildcard $(JOBS_DIR)/*.env)
JOBS:=$(patsubst $(JOBS_DIR)/%.env,%,$(JOB_PARAM_FILES))

OC_CMD=$(OC) $(OCFLAGS)

help:
	@echo TARGETS
	@echo -e "\tinstall\t\tInstall or update pipelines to OpenShift"
	@echo -e "\tuninstall\tDelete installed pipelines from OpenShift"
	@echo
	@echo VARIABLES
	@echo -e "\tJOBS\t\tSpace seperated list of pipeline jobs to install"
	@echo -e "\tJOBS_DIR\tLooking for pipeline job definitions in an alternate directory."
	@echo -e "\tTEMPLATES_DIR\tLooking for pipeline job templates in an alternate directory."
	@echo -e "\tOC\t\tUse this oc command"
	@echo -e "\tOCFLAGS\t\tOptions to append to the oc command arguments"
install:
	@$(OC_CMD) project
	@for job in $(JOBS); do \
		echo "[PIPELINE] Updating pipeline job \"$${job}\"..." ; \
	  template_file=$$(cat ./$(JOBS_DIR)/$${job}.tmpl); \
		$(OC_CMD) process --local -f ./$(TEMPLATES_DIR)/$${template_file} \
			--param-file ./$(JOBS_DIR)/$${job}.env | $(OC_CMD) apply -f -; \
		echo "[PIPELINE] Pipeline job \"$${job}\" updated" ; \
	done
uninstall:
	@$(OC_CMD) project
	@for job in $(JOBS); do \
	  template_file=$$(cat ./$(JOBS_DIR)/$${job}.tmpl); \
		template_name=$${template_file%.y?ml}; \
		template_name=$${template_name%-template}; \
		echo "[PIPELINE] Deleting pipeline job \"$${job}\"..." ; \
		$(OC_CMD) delete all -l template="$$template_name" -l app="$$job" ;\
		echo "[PIPELINE] Pipeline job \"$${job}\" deleted" ; \
	done
create-jenkins-is:
	$(OC_CMD) import-image jenkins:2 --confirm --scheduled=true \
		--from=registry.access.redhat.com/openshift3/jenkins-2-rhel7:v3.11
install-jenkins: create-jenkins-is
	$(OC_CMD) new-app --template=jenkins-persistent \
		-p MEMORY_LIMIT=2Gi \
		-p VOLUME_CAPACITY=10Gi \
		-p NAMESPACE=$(shell $(OC_CMD) project -q) \
		-e INSTALL_PLUGINS=script-security:1.46,permissive-script-security:0.3,timestamper:1.9,http_request:1.8.22,ownership:0.12.1,antisamy-markup-formatter:1.5,update-sites-manager:2.0.0 \
		-e JENKINS_JAVA_OVERRIDES="-Dpermissive-script-security.enabled=no_security"
update-pagure-api-key:
	[ -n "$(KEY)" ] # You must specify KEY=<key value>
	$(OC_CMD) delete secret pagure-api-key --ignore-not-found=true
	$(OC_CMD) create secret generic pagure-api-key --from-literal=secrettext=$(KEY)
	$(OC_CMD) label secret pagure-api-key credential.sync.jenkins.openshift.io=true
.PHONY: help install uninstall create-jenkins-is install-jenkins update-api-key
