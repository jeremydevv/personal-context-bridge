import tempfile
import unittest
from pathlib import Path
from personal_context.location_dictionary import LocationDictionary, build_stays
from personal_context.subscription_auth import PrivateState


def point(i,t,lat=40.0,lon=-75.0,accuracy=5):
    return dict(id=str(i),timestamp=t,latitude=lat,longitude=lon,accuracy_m=accuracy)

class PlaceTests(unittest.TestCase):
    def test_gap_and_drive_through_not_visits(self):
        self.assertEqual(build_stays([point(1,0),point(2,36000)]),[])
        self.assertEqual(build_stays([point(1,0),point(2,60,lat=40.1)]),[])
        self.assertEqual(len(build_stays([point(1,0),point(2,600)])),1)
        self.assertEqual(build_stays([point(1,0,accuracy=800),point(2,600)]),[])
    def test_stable_name_replay_and_correction(self):
        with tempfile.TemporaryDirectory() as d:
            dictionary=LocationDictionary(PrivateState(Path(d),b'z'*32))
            points=[point(1,1000),point(2,1600)]
            dictionary.update(points)
            p=dictionary.search()['places'][0]
            dictionary.correct(p['place_id'],title='My Library',aliases=['Study spot'])
            dictionary.update(points+[point(3,8000),point(4,8600)])
            after=dictionary.search('Study spot')['places'][0]
            self.assertEqual(after['place_id'],p['place_id'])
            self.assertEqual(after['title'],'My Library')
            self.assertEqual(after['visit_count'],2)
            self.assertEqual(len(dictionary.visits(p['place_id'])['visits']),2)
            self.assertIn('unknown',after['visit_reason'])
    def test_missing_accuracy_and_future_are_not_assigned(self):
        self.assertEqual(build_stays([point(1,100,accuracy=None),point(2,800,accuracy=None)]),[])

class ObservedPlaceTests(unittest.TestCase):
    def test_single_observation_is_searchable_but_not_a_confirmed_stay(self):
        with tempfile.TemporaryDirectory() as d:
            dictionary=LocationDictionary(PrivateState(Path(d),b'r'*32))
            dictionary.update([point(1,1000)])
            p=dictionary.search()['places'][0]
            self.assertEqual(p['visit_count'],0)
            self.assertEqual(p['observation_count'],1)
            self.assertIn('unconfirmed',p['presence'])

class FreshnessTests(unittest.TestCase):
    def test_waypoint_does_not_refresh_gps(self):
        import sqlite3,time
        from iphone_context.location_receiver import SCHEMA
        from iphone_context.queries import TravelQueries
        c=sqlite3.connect(':memory:');c.executescript(SCHEMA)
        old=int(time.time())-864000;now=int(time.time())
        c.execute("INSERT INTO events(digest,event_type,event_ts,received_ts,payload) VALUES('gps','location',?,?, '{}')",(old,old))
        c.execute("INSERT INTO events(digest,event_type,received_ts,payload) VALUES('waypoint','waypoints',?,'{}')",(now,))
        status=TravelQueries(c).status()
        self.assertEqual(status['last_received_unix'],now)
        self.assertEqual(status['last_location_received_unix'],old)
        self.assertEqual(status['location_freshness'],'stale_or_stationary')
        self.assertEqual(status['location_receipts_7d'],0)

class CorrectionTests(unittest.TestCase):
    def test_description_correction_survives_reprocessing(self):
        with tempfile.TemporaryDirectory() as d:
            dictionary=LocationDictionary(PrivateState(Path(d),b's'*32));points=[point(1,1000)]
            dictionary.update(points);pid=dictionary.search()['places'][0]['place_id']
            dictionary.correct(pid,description='My confirmed meeting place')
            dictionary.update(points)
            self.assertEqual(dictionary.detail(pid)['place']['description'],'My confirmed meeting place')
