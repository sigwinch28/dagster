from pathlib import Path
from typing import Dict

from setuptools import find_packages, setup


def get_version() -> str:
    version: Dict[str, str] = {}
    with open(Path(__file__).parent / "dagster_celery_docker/version.py", encoding="utf8") as fp:
        exec(fp.read(), version)

    return version["__version__"]


ver = get_version()
# dont pin dev installs to avoid pip dep resolver issues
pin = "" if ver == "1!0+dev" else f"=={ver}"
setup(
    name="dagster-celery-docker",
    version=ver,
    author="Elementl",
    license="Apache-2.0",
    description="A Dagster integration for celery-docker",
    url="https://github.com/dagster-io/dagster/tree/master/python_modules/libraries/dagster-celery-docker",
    classifiers=[
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: OS Independent",
    ],
    packages=find_packages(exclude=["dagster_celery_docker_tests*"]),
    install_requires=[
        "dagster==1.3.14rc1",
        "dagster-celery==0.19.14rc1",
        "dagster-graphql==1.3.14rc1",
        "docker",
    ],
    zip_safe=False,
)
