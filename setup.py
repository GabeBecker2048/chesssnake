from setuptools import setup

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

with open('requirements-postgres.txt') as f:
    requirements_postgres = f.read().splitlines()

with open('requirements-postgres-binary.txt') as f:
    requirements_postgres_binary = f.read().splitlines()

with open('README.md') as f:
    README = f.read()

setup(
    name="ChessPy",
    version="0.1.0",
    url="https://github.com/GabeBecker2048/chessql",
    description="A Python library for playing, visualizing, and storing chess games.",
    author="Gabe Becker",
    author_email="gabebecker2048@gmail.com",
    long_description=README,
    long_description_content_type='text/markdown',
    license="MIT",
    packages=["ChessPy"],
    include_package_data=True,
    install_requires=requirements,
    package_data={
        "chesslib/data": ["*.sql", "*.ttf", "img/*.png"],
    },
    extras_require={
        "postgres": requirements_postgres,
        "postgres-binary": requirements_postgres_binary,
    },
    python_requires='>=3.9',
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
