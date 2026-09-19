#!/usr/bin/env python3

import unittest

import pandas as pd

from train_esa_cdm import build_event_table


class EventTableTest(unittest.TestCase):
    def test_label_row_is_never_reused_as_feature(self) -> None:
        raw = pd.DataFrame(
            [
                {"event_id": 1, "time_to_tca": 4.0, "risk": -8.0, "mission_id": 1, "c_object_type": "DEBRIS"},
                {"event_id": 1, "time_to_tca": 3.0, "risk": -7.0, "mission_id": 1, "c_object_type": "DEBRIS"},
                {"event_id": 1, "time_to_tca": 0.5, "risk": -4.0, "mission_id": 1, "c_object_type": "DEBRIS"},
                # The final row itself is older than the two-day cutoff. It is
                # still a label and must not become the latest input feature.
                {"event_id": 2, "time_to_tca": 4.0, "risk": -9.0, "mission_id": 2, "c_object_type": "UNKNOWN"},
                {"event_id": 2, "time_to_tca": 2.5, "risk": -5.0, "mission_id": 2, "c_object_type": "UNKNOWN"},
            ]
        )
        events = build_event_table(raw, with_target=True).set_index("event_id")
        self.assertEqual(events.loc[1, "last_risk"], -7.0)
        self.assertEqual(events.loc[1, "final_risk_log10"], -4.0)
        self.assertEqual(events.loc[2, "last_risk"], -9.0)
        self.assertEqual(events.loc[2, "final_risk_log10"], -5.0)


if __name__ == "__main__":
    unittest.main()
