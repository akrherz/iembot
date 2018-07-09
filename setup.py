from distutils.core import setup
from setuptools.command.test import test as TestCommand
import sys
import iembot


class PyTest(TestCommand):
    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import pytest
        errno = pytest.main(self.test_args)
        sys.exit(errno)


setup(
    name='iembot',
    version=iembot.__version__,
    author='daryl herzmann',
    author_email='akrherz@gmail.com',
    packages=['iembot', ],
    package_data={'iembot': ['data/*', ]},
    url='https://github.com/akrherz/iembot/',
    license='Apache',
    cmdclass={'test': PyTest},
    description=('A hacky XMPP Bot'),
)
