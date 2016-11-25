from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.readlines()

with open('test-requirements.txt') as f:
    test_requirements = f.readlines()

setup(name='module-build-service',
      description='The Module Build Service for Modularity',
      version='1.0.0',
      classifiers=[
          "Programming Language :: Python",
          "Topic :: Software Development :: Build Tools"
      ],
      keywords='module build service fedora modularity koji mock rpm',
      author='FIXME',
      author_email='FIXME',
      url='https://pagure.io/fm-orchestrator/',
      license='GPLv2+',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requirements,
      tests_require=test_requirements,
      entry_points={
          'console_scripts': ['module_build_service_daemon = module_build_service.scheduler.main:main',
                              'module_build_service_upgradedb = module_build_service.manage:upgradedb']
      },
      data_files=[('/etc/module-build-service/', ['conf/cacert.pem',
                                                  'conf/config.py',
                                                  'conf/copr.conf',
                                                  'conf/koji.conf']),
                  ('/etc/module-build-service/fedmsg.d/', ['fedmsg.d/logging.py',
                                                           'fedmsg.d/module_build_service.py']),
                  ],
      )
