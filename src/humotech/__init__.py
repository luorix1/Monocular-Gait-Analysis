"""Humotech Gait Analysis: single-camera treadmill gait analysis.

video -> 2D keypoints -> 3D lift -> treadmill-constrained refinement -> OpenSim scale/IK
      -> gait events -> spatiotemporal parameters (+ belt speed estimated from the stance foot)
"""
__version__ = "0.1.0"
