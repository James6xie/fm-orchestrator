from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.readlines()

with open('test-requirements.txt') as f:
    test_requirements = f.readlines()

setup(name='module-build-service',
      description='The Module Build Service for Modularity',
      version='1.4.6',
      classifiers=[
          "Programming Language :: Python",
          "Topic :: Software Development :: Build Tools"
      ],
      keywords='module build service fedora modularity koji mock rpm',
      author='The Factory 2.0 Team',
      author_email='module-build-service-owner@fedoraproject.org',
      url='https://pagure.io/fm-orchestrator/',
      license='MIT',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requirements,
      tests_require=test_requirements,
      entry_points={
          'console_scripts': ['mbs-upgradedb = module_build_service.manage:upgradedb',
                              'mbs-frontend = module_build_service.manage:run',
                              'mbs-manager = module_build_service.manage:manager_wrapper'],
          'moksha.consumer': 'mbsconsumer = module_build_service.scheduler.consumer:MBSConsumer',
          'moksha.producer': 'mbspoller = module_build_service.scheduler.producer:MBSProducer',
          'mbs.messaging_backends': [
              'fedmsg = module_build_service.messaging:_fedmsg_backend',
              'in_memory = module_build_service.messaging:_in_memory_backend',
              # 'custom = your_organization:_custom_backend',
          ],
          'mbs.builder_backends': [
              'koji = module_build_service.builder.KojiModuleBuilder:KojiModuleBuilder',
              'mock = module_build_service.builder.MockModuleBuilder:MockModuleBuilder',
              # TODO - let's move this out into its own repo so @frostyx can
              # iterate without us blocking him.
              'copr = module_build_service.builder.CoprModuleBuilder:CoprModuleBuilder',
          ],
      },
      scripts=["contrib/mbs-build"],
      data_files=[('/etc/module-build-service/', ['conf/cacert.pem',
                                                  'conf/config.py',
                                                  'conf/copr.conf',
                                                  'conf/koji.conf',
                                                  'conf/mock.cfg',
                                                  'conf/yum.conf']),
                  ('/etc/fedmsg.d/', ['fedmsg.d/mbs-logging.py',
                                      'fedmsg.d/mbs-scheduler.py',
                                      'fedmsg.d/module_build_service.py']),
                  ],
      )
