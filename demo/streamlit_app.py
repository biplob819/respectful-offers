# Respectful Offers demo page (deploy bundle, DEM-03). All outcomes are simulated.
import os
from pathlib import Path

os.environ.setdefault("OFFERS_DEMO_CUBE", str(Path(__file__).with_name("cube.json")))

from respectful_offers.demo.app import main

main()
