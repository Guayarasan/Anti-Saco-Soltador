from endstone_antidupe.detection.detectors.bundle_container import BundleContainerDetector
from endstone_antidupe.detection.detectors.bundle_ground import BundleGroundDetector

ALL_DETECTORS = [BundleContainerDetector, BundleGroundDetector]

__all__ = ["BundleContainerDetector", "BundleGroundDetector", "ALL_DETECTORS"]
