import os
import sys
import copy
import json
import time
import arrow
import argparse
import requests
from enum import Enum

import config

class TrendDirection(Enum):
    DoubleDown = -3    # ↓↓ This may exist, but never was seen
    SingleDown = -2    # ↓
    FortyFiveDown = -1 # ↘
    Flat = 0           # →
    FortyFiveUp = 1    # ↗
    SingleUp = 2       # ↑
    DoubleUp = 3       # ↑↑ This may exist, but never was seen

# Data type for the payload returned by https://<SiBionic>/follow/app/<id>/v2
class GlucoseData:
    def __init__(self, json_data=None):
        self.updateTime = None
        self.deviceName = None
        self.latestGlucoseTime = None
        self.data = {}
        if json_data:
            oldest_precision_timestamp = int(json_data['data']['followedDeviceGlucoseDataPO']['latestGlucoseTime'])
            # glucoseInfo only has the precision timestamp within 24 hours
            for glucoseInfo in json_data['data']['followedDeviceGlucoseDataPO']['glucoseInfos']:
                if glucoseInfo['effective']:
                    self.add_record(glucoseInfo['t'], glucoseInfo['v'], glucoseInfo['s'])
                    if glucoseInfo['t'] < oldest_precision_timestamp:
                        oldest_precision_timestamp = glucoseInfo['t']
            # glucose data longer than 24 hours will be archived to dailyData, and timestamp will be
            # rounded to nearest mintute
            archived_maximum_timestamp, _ = GlucoseData.get_archive_timestamp(oldest_precision_timestamp)
            for dailyData in json_data['data']['followedDeviceGlucoseDataPO']['dailyData']:
                for item in dailyData['data']:
                    # Skip this entry as it's already covered in glucoseInfo
                    if item['t'] >= archived_maximum_timestamp:
                        continue
                    if item['effective'] and item['t'] not in self.data:
                        self.add_record(item['t'], item['v'])
            self.updateTime = json_data['timestamp']
            self.deviceName = json_data['data']['followedDeviceGlucoseDataPO']['deviceName']
            self.latestGlucoseTime = int(json_data['data']['followedDeviceGlucoseDataPO']['latestGlucoseTime'])

    def add_record(self, timestamp, value, trend=None):
        if timestamp in self.data:
            if self.data[timestamp] != (value, trend):
                raise ValueError(f"Error: Record with timestamp {timestamp} already exists with a different value")
        else:
            self.data[timestamp] = (value, trend)

    @classmethod
    def get_archive_timestamp(cls, timestamp):
        remainder = timestamp % (1000 * 60)
        round_down_minute = timestamp - remainder
        round_up_minute = timestamp + (1000 * 60 - remainder)
        # A timestamp will either be round down or up to nearest minute
        return round_down_minute, round_up_minute

    @classmethod
    def get_new_data_after_time(cls, cur_glucose_data, timestamp):
        if not isinstance(cur_glucose_data, cls):
            raise TypeError("Error: Input parameter must be an instance of the same class as the object")

        dt = arrow.get(timestamp)
        new_data = copy.copy(cur_glucose_data)
        new_data.data = {k: v for k, v in cur_glucose_data.data.items() if arrow.get(k) > dt}
        return new_data

    @classmethod
    def compare_and_get_new_data(cls, cached_glucose_data, updated_glucose_data):
        if not isinstance(cached_glucose_data, cls) or not isinstance(updated_glucose_data, cls):
            raise TypeError("Error: Input parameter must be an instance of the same class as the object")
        if updated_glucose_data.deviceName != cached_glucose_data.deviceName:
            raise Exception(f"Error: data is coming from a new device: {updated_glucose_data.deviceName}. Current device: {cached_glucose_data.deviceName}")

        not_present_data = {}
        not_match_data = {}
        for timestamp, value in cached_glucose_data.data.items():
            # Any data entry in cached glucose data could either be: a) still with precision timestamp; b) be archived(rounded) in updated glucose_data
            rounddown_time, roundup_time = cls.get_archive_timestamp(timestamp)
            if not any(t in updated_glucose_data.data for t in [timestamp, rounddown_time, roundup_time]):
                not_present_data[timestamp] = value
            else:
                new_timestamp = next(t for t in [timestamp, rounddown_time, roundup_time] if t in updated_glucose_data.data)
                new_value = updated_glucose_data.data[new_timestamp]
                if value[0] != new_value[0]:
                   v, t = value
                   n_v, n_t = updated_glucose_data.data[new_timestamp]
                   not_match_data[timestamp] = (v, t, n_v, n_t)

        if not_present_data:
            msg_missing_entry = '\n'.join([f"Timestamp: {timestamp}, Value: {value}" for timestamp, value in not_present_data.items()])
            raise Exception(f"Validation Error: Existing data not present in the updated data: {msg_missing_entry}")
        if not_match_data:
            msg_not_match = '\n'.join([f"Timestamp: {timestamp}, Value: {value}" for timestamp, value in not_match_data.items()])
            raise Exception(f"Validation Error: Existing data entries not match with the updated data: {msg_not_match}")

        new_data = copy.copy(updated_glucose_data)
        # Extract new data from updated_glucose
        new_data.data = {k: v for k, v in updated_glucose_data.data.items() if k not in cached_glucose_data.data}
        # A data point with precision timestamp in cache, could become archived in updated glucose data
        # For example:
        #     updated:                 (ta, v, -), (ta, v, -), (ts, v, s)
        #     cache:       (ta, v, -)  (ts, v, s)
        # In that case, we also need to exclude that from updated_glucose
        for k, v in cached_glucose_data.data.items():
            rd_k, ru_k = cls.get_archive_timestamp(k)
            if rd_k in updated_glucose_data.data:
                del updated_glucose_data.data[rd_k]
            if ru_k in updated_glucose_data.data:
                del updated_glucose_data.data[ru_k]
        # Be noted, the data could still be empty
        return new_data

    def extend(self, other_glucose_data):
        if not isinstance(other_glucose_data, GlucoseData):
            raise TypeError("Error: Input parameter must be an instance of the same class as the object")

        for timestamp, value in other_glucose_data.data.items():
            if timestamp not in self.data:
                self.data[timestamp] = value

    def __str__(self):
        return '\n'.join([f"Timestamp: {timestamp}, Value: {value}" for timestamp, value in self.data.items()])

def bg_mmol_to_mgdl(value):
    return round(value * 18.018018)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache_dir', help="Directory where the cache data will be saved. E.g., /usr/local/data/cgm/", required=False)
    parser.add_argument('--delay', type=int, help="Delay number of seconds before execution", required=False)
    args = parser.parse_args()
    cache_dir = os.path.join(os.getcwd(), 'cache')
    if args.cache_dir is not None:
        cache_dir = args.cache_dir
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)

    response = requests.get(config.SIBIONIC_URL_FOLLOWED_USER_DATA, headers={'Authorization':config.SIBIONIC_ACCESS_TOKEN})
    if not response.ok:
        print("Error! SiBionic API access failed!")
        sys.exit(-1)
    content = json.loads(response.text)
    if content['code'] != 200:
        print("Error! SiBionic API access failed. Code: {}; Message: {}".format(content['code'], content['msg']))
        sys.exit(-1)
    data_latest = GlucoseData(content)

    # Every time the program executes, it reads the cache, and then make the API call to compare it with cache
    #   1. If this is a new device
    #   2. If this is an existing device, but with updated data
    #   3. If this is an existing device, but no new data
    cacheFile = os.path.join(cache_dir, data_latest.deviceName)
    data_cached = None
    data_to_process = None
    if os.path.exists(cacheFile):
        with open(cacheFile, 'r') as f:
            data_cached = GlucoseData(json.load(f))
    if data_cached:
        print("Found cache for device {}, it was read at {}".format(data_cached.deviceName,
                                                                    arrow.get(data_cached.latestGlucoseTime).humanize()))
        data_to_process = GlucoseData.compare_and_get_new_data(data_cached, data_latest)
    else:
        print("No cache data for device {}".format(data_latest.deviceName))
        data_to_process = data_latest

    if args.delay is not None:
        print("Delaying {} seconds...".format(args.delay))
        time.sleep(args.delay)
    else:
        if data_cached:
            print("Adjusting pace based on the sensor reading pace in cache...")
            s_delay = int(data_cached.latestGlucoseTime / 1000) % (60 * 5)
            print("Sensor reading happens {} seconds after every 5 minutes".format(s_delay))
            now = int(time.time())
            c_delay = now % (60 * 5)
            print("Current time is {} seconds after every 5 minutes".format(c_delay))
            if s_delay < c_delay and c_delay - s_delay < 60 * 2:
                print("Sensor reading should've been updated within 2 minutes")
            else:
                delay = (s_delay - c_delay + 60 * 5) % (60 * 5)
                print("Delay {} seconds for next reading".format(delay))
                time.sleep(delay)
                time.sleep(5) # 5 more seconds for the data to be uploaded to server
        else:
            print("Not delaying...")

    dt = arrow.get(data_latest.latestGlucoseTime)
    print('Most recent glucose data was read at {}'.format(dt.humanize()))

    # Filter out those records already in NightScout
    response = requests.get(config.NIGHTSCOUT_API_EP_ENTRIES,
                            headers={'api-secret': config.NIGHTSCOUT_API_SECRET,
                                     'Accept': 'application/json'})
    if not response.ok:
        print('Failed to read historical entries from {}'.format(config.NIGHTSCOUT_API_EP_ENTRIES))
        print('  Error: {}'.format(response.text))
    else:
        data_recorded = json.loads(response.text)
        most_recent_gd = 0
        # NightScout API doesn't return all the entries by default, therefore we get the most recent
        # record, and assume all data before that time were properly recorded
        for record in data_recorded:
            most_recent_gd = record['date'] if record['date'] > most_recent_gd else most_recent_gd
        if most_recent_gd != 0:
            print('Nightscout recorded most recent historical data at {}'.format(arrow.get(most_recent_gd).humanize()))
            data_to_process = GlucoseData.get_new_data_after_time(data_to_process, most_recent_gd)

    # Processing new data:
    if not data_to_process.data:
        print("No new data to process")
        sys.exit(0)
    else:
        print("Processing {} new entries.".format(len(data_to_process.data)))
        entries = []
        for timestamp, value in data_to_process.data.items():
            reading, trend = value
            bg_mgdl = bg_mmol_to_mgdl(reading)

            entry = dict(type="sgv",
                         sgv=bg_mgdl,
                         date=timestamp,
                         dateString=arrow.get(timestamp).to('Asia/Shanghai').isoformat())
            if trend is not None:
                entry['direction'] = TrendDirection(trend).name
            entries.append(entry)

        print("Ready to post: {}".format(entries))
        response = requests.post(config.NIGHTSCOUT_API_EP_ENTRIES,
                                 headers={'api-secret':config.NIGHTSCOUT_API_SECRET},
                                 json=entries)
        if response.ok:
            print("Successfully uploaded {} entries!!!".format(len(entries)))
            with open(cacheFile, 'w') as file:
                json.dump(content, file, indent=4)
                print("Saving data to {}".format(data_latest.deviceName))
        else:
            print("Upload failed. {}".format(response.text))

