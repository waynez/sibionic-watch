import os
import sys
import copy
import json
import time
import arrow
import argparse
import requests

import config

# Data type for the payload returned by https://<SiBionic>/follow/app/<id>/v2
class GlucoseData:
    def __init__(self, json_data=None):
        self.updateTime = None
        self.deviceName = None
        self.latestGlucoseTime = None
        self.data = {}
        if json_data:
            for dailyData in json_data['data']['followedDeviceGlucoseDataPO']['dailyData']:
                for item in dailyData['data']:
                    self.add_record(item['t'], item['v'], item['effective'])
            self.updateTime = json_data['timestamp']
            self.deviceName = json_data['data']['followedDeviceGlucoseDataPO']['deviceName']
            self.latestGlucoseTime = json_data['data']['followedDeviceGlucoseDataPO']['latestGlucoseTime']

    def add_record(self, timestamp, value, effective):
        if timestamp in self.data:
            if self.data[timestamp] != (value, effective):
                raise ValueError(f"Error: Record with timestamp {timestamp} already exists with a different value")
        else:
            self.data[timestamp] = (value, effective)

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
            if timestamp not in updated_glucose_data.data:
                not_present_data[timestamp] = value
            elif value != updated_glucose_data.data[timestamp]:
                v, e = value
                n_v, n_e = updated_glucose_data.data[timestamp]
                not_match_data[timestamp] = (v, e, n_v, n_e)

        if not_present_data:
            msg_missing_entry = '\n'.join([f"Timestamp: {timestamp}, Value: {value}" for timestamp, value in not_present_data.items()])
            raise Exception(f"Validation Error: Existing data not present in the updated data: {msg_missing_entry}")
        if not_match_data:
            msg_not_match = '\n'.join([f"Timestamp: {timestamp}, Value: {value}" for timestamp, value in not_match_data.items()])
            raise Exception(f"Validation Error: Existing data entries not match with the updated data: {msg_not_match}")

        new_data = copy.copy(updated_glucose_data)
        # Be noted, the data could still be empty
        new_data.data = {k: v for k, v in updated_glucose_data.data.items() if k not in cached_glucose_data.data}
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
    return value * 18.018018

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cache_dir', help="Directory where the cache data will be saved. E.g., /usr/local/data/cgm/", required=False)
    parser.add_argument('--delay', type=int, help="Delay number of seconds before execution", required=False)
    args = parser.parse_args()
    if args.delay is not None:
        print("Delaying {} seconds...".format(args.delay))
        time.sleep(args.delay)
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
    with open(cacheFile, 'w') as file:
        json.dump(content, file, indent=4)
        print("Saving data to {}".format(data_latest.deviceName))
    if data_cached:
        print("Found cache for device {}, it was read at {}".format(data_cached.deviceName,
                                                                    arrow.get(int(data_cached.latestGlucoseTime)).humanize()))
        data_to_process = GlucoseData.compare_and_get_new_data(data_cached, data_latest)
    else:
        print("No cache data for device {}".format(data_latest.deviceName))
        data_to_process = data_latest

    dt = arrow.get(int(data_latest.latestGlucoseTime))
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
            reading, valid = value
            if not valid:
                print("  - Found invalid data, t: {}, v: {}, effective: {}", timestamp, reading, valid)
                continue
            bg_mgdl = bg_mmol_to_mgdl(reading)

            entries.append(dict(type="sgv",
                                sgv=int(bg_mgdl),
                                date=timestamp,
                                dateString=arrow.get(timestamp).to('Asia/Shanghai').isoformat()))

        response = requests.post(config.NIGHTSCOUT_API_EP_ENTRIES,
                                 headers={'api-secret':config.NIGHTSCOUT_API_SECRET},
                                 json=entries)
        if response.ok:
            print("Successfully uploaded {} entries!!!".format(len(entries)))
        else:
            print("Upload failed. {}".format(response.text))

