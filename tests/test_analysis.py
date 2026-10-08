"""Analysis tests."""
import unittest
import numpy as np

from analysis.rating_curve import fit_power_law

class TestAnalysis(unittest.TestCase):
    def test_power_law(self):
        x = np.array([1, 10, 100])
        y = np.array([2.5, 250, 25000])
        fit = fit_power_law(x, y)
        self.assertAlmostEqual(fit.a, 2.5)
        self.assertAlmostEqual(fit.b, 2.0)

if __name__ == "__main__":
    unittest.main()
