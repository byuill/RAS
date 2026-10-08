"""Unit conversions tests."""
import unittest
import math

from sediment.units import from_canonical, to_canonical, concentration_from_flux, M3_PER_CFS

class TestUnits(unittest.TestCase):
    def test_flux_conc(self):
        # 1 mg/L * 1 cfs = 0.0026969 tons/day
        # cfs to m3/s -> 1 * 0.0283168
        # mg/L to kg/m3 -> 1 * 0.001
        # flux kg/s = 0.0000283168
        # kg/s to tons/day: kg/s * 86400 / 907.1847 = 2.69688 * 10^-3
        c = 1.0 # mg/L
        q = 1.0 * M3_PER_CFS # m3/s
        
        flux_kg_s = c * 0.001 * q
        flux_tons_day = from_canonical(flux_kg_s, "mass_flux", "tons/day")
        self.assertAlmostEqual(flux_tons_day, 0.0026968879, places=6)
        
    def test_round_trip(self):
        val = 123.45
        kg_s = to_canonical(val, "tons/day")
        val2 = from_canonical(kg_s, "mass_flux", "tons/day")
        self.assertAlmostEqual(val, val2)

if __name__ == "__main__":
    unittest.main()
