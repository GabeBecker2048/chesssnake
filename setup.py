from setuptools import setup, find_packages

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

with open('extra_requirements/requirements-postgres.txt') as f:
    requirements_postgres = f.read().splitlines()

with open('extra_requirements/requirements-postgres-binary.txt') as f:
    requirements_postgres_binary = f.read().splitlines()

with open('README.md') as f:
    README = f.read()

setup(
    name="chesssnake",
    version="0.5.3",
    url="https://github.com/GabeBecker2048/chesssnake",
    description="A Python library for playing, visualizing, and storing chess games.",
    author="Gabe Becker",
    author_email="gabebecker2048@gmail.com",
    long_description=README,
    long_description_content_type='text/markdown',
    license="MIT",
    packages=find_packages(),
    include_package_data=True,
    install_requires=requirements,
    package_data={
        "chesssnake": ["data/*.sql", "data/*.ttf", "data/img/*.png"],
    },
    extras_require={
        "postgres": requirements_postgres,
        "postgres-binary": requirements_postgres_binary,
    },
    python_requires='>=3.9',
    classifiers=[
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3.13",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
