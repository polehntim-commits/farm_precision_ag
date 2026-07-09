from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

# get version from __version__ variable in farm_precision_ag/__init__.py
from farm_precision_ag import __version__ as version

setup(
    name="farm_precision_ag",
    version=version,
    description=(
        "Precision agriculture module for ERPNext. Phase B: USDA Market "
        "Pricing — cached commodity prices from the USDA MARS API."
    ),
    author="Polehn Farm",
    author_email="polehntim@gmail.com",
    license="MIT",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
