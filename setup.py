from setuptools import setup, find_packages

setup(
    name="inferacap",
    version="1.0.0",
    description="The Economically-Aware Multi-Region Inference Load Balancer",
    author="Bhaskar Pandey",
    author_email="bhaskarauthor@gmail.com",
    url="https://github.com/bhaskarpandey/inferacap",
    packages=find_packages(),
    py_modules=[
        "inferacap",
        "run_gateway",
        "scan_logs",
        "demo_inferacap",
        "demo_terminal_walkthrough",
        "sw004_simulator",
        "sw004_ui",
        "sw004_sensitivity",
        "benchmark_sw004",
    ],
    entry_points={
        "console_scripts": [
            "inferacap-gateway=run_gateway:main",
            "inferacap-scan=scan_logs:main",
            "inferacap-demo=demo_inferacap:run_demo",
            "inferacap-showcase=demo_terminal_walkthrough:main",
            "inferacap-kaggle=gateway.inferacap_kaggle_worker:main",
        ],
    },
    python_requires=">=3.9",
    install_requires=[],
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.12",
    ],
)
