"""The Tokyo editorial batch must remain traceable and adoptable as draft data."""

import unittest

from core.pilot import load_pilot
from core.place_links import trip_eligible
from core.trip_adoption import draft_from_legacy


NEW_WORKS = {'296659', '387803', '428735', '369304', '2463', '306742'}


class TokyoExpansionTests(unittest.TestCase):
    def test_selected_source_records_have_one_canonical_place_and_scene(self):
        data = load_pilot()
        self.assertTrue(NEW_WORKS <= {work['id'] for work in data['anime']})
        new_places = [place for place in data['locations'] if place['reviewed_at'] == '2026-09-30']
        source_to_place = {}
        for place in new_places:
            self.assertTrue(trip_eligible(place, data))
            self.assertEqual(place['access']['status'], 'unknown')
            for source in place['upstream']:
                key = (source['anime_id'], source['record_id'])
                self.assertNotIn(key, source_to_place)
                source_to_place[key] = place['id']
        scenes = [scene for scene in data['scenes'] if scene['anime_id'] in NEW_WORKS]
        self.assertEqual(len(new_places), 21)
        self.assertEqual(len(source_to_place), 27)
        self.assertEqual(len(scenes), 27)
        for scene in scenes:
            self.assertEqual(source_to_place[(scene['anime_id'], scene['upstream_record_id'])], scene['location_id'])
            self.assertEqual(scene['match_status'], 'community_reported')
            self.assertFalse(scene['media']['display_allowed'])

    def test_shared_park_and_new_handbook_can_enter_editable_trip(self):
        data = load_pilot()
        park = next(place for place in data['locations'] if place['id'] == 'loc-tokyo-higashi-ikebukuro-central-park')
        self.assertEqual(set(park['anime_ids']), {'428735', '2463'})
        self.assertEqual(len(park['upstream']), 3)
        route = next(route for route in data['routes'] if route['id'] == 'route-ikebukuro-parks')
        self.assertFalse(route['publication']['field_verified'])
        self.assertTrue(all(connection['duration_min'] is None for connection in route['connections']))
        items = [{'id': stop['location_id'], 'required': stop['required'], 'stay_max': stop['stay_max']}
                 for stop in route['stops']]
        plan = draft_from_legacy(items, data, selected_ids=[item['id'] for item in items],
                                 start_date='2026-10-01', day_count=1, title='池袋公园草案')
        self.assertEqual([stop['location_id'] for stop in plan['days'][0]['stops']],
                         [item['id'] for item in items])
        self.assertEqual(set(plan['requirements']['anime_ids']), {'428735', '2463'})


if __name__ == '__main__':
    unittest.main()
