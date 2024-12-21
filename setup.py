from setuptools import setup

with open('requirements.txt') as f:
    requirements = f.read().splitlines()

with open('README.md') as f:
    README = f.read()

setup(
    version="0.1.0",
    url="https://github.com/GabeBecker2048/chessql",
    description="A Python library for playing, visualizing, and storing chess games.",
    author="Gabe Becker",
    author_email="gabebecker2048@gmail.com",
    long_description=README,
    long_description_content_type='text/markdown',
    license="MIT",
    include_package_data=True,
    install_requires=requirements,
    package_data={
    },
    python_requires='>=3.9',
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
