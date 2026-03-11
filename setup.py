"""Setup configuration for alpaca-cli."""

from setuptools import setup, find_packages

setup(
    name="alpaca-papertrading-cli",
    version="0.1.0",
    description="Paper trading CLI for stocks & crypto via Alpaca, with technical indicators and custom strategies",
    author="serenakeyitan",
    url="https://github.com/serenakeyitan/alpaca-papertrading-CLI",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "click>=8.0",
        "alpaca-py>=0.21.0",
        "python-dotenv>=1.0",
        "rich>=13.0",
    ],
    extras_require={
        "dev": [
            "pytest",
            "ruff",
        ],
    },
    entry_points={
        "console_scripts": [
            "alpaca=alpaca_cli.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Office/Business :: Financial :: Investment",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
