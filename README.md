# Introduction

If you're a SiBionics CGM sensor user, and are using the SiBionics APP, you might be wondering how to upload the data into your NightScout service. However the mainstream BG upload solution like xDrip+ has not yet supported SiBionics CGM, so the project was initiated aiming to provide a solution for SiBionics users.

## Prerequisites

- A NightScout web service to upload data
- A SiBionics CGM and registered SiBionics APP user account
- **Important:** SiBionics APP's 'follow others' feature is available at your region. This feature allows a user to share his/her glucose data with others, and is used by this project to retrieve the data from SiBionics servers

# Before running

Modify `config.py`, fill in all the values to access your web service provider's APIs

- `SIBIONIC_ACCESS_TOKEN`: The access token to access SiBionics API
- `SIBIONIC_URL_FOLLOWED_USER_DATA`: API URL to fetch data from SiBionics, E.g., 'https://api.sisensing.com/follow/app/<uid>/v2'
- `NIGHTSCOUT_API_EP_ENTRIES`: NightScout API URL to upload CGM data, E.g., 'https://<nightscout_base_url>/api/v1/entries'
- `NIGHTSCOUT_API_SECRET`: NightScout API secret, this is the hashed API secret to access NightScout API

# Running
```
python process.py
```

Run with a dedicated directory for cache saving
```
python process.py --cache_dir=/path/to/cache/dir/
```

# Using docker

Note: Please use a local config.py to override the default config.py built in the container image
```
docker build -t sibionic-watch:latest .
docker run -d -v /path/to/local/config.py:/app/config.py sibionic-watch
```

Optionally, you can use a local cache dir to persist caches
```
docker run -d -v /path/to/local/config.py:/app/config.py -v /path/to/local/cache/dir/:/app/cache/ sibionic-watch
```

# How it works

1. It reads the SiBionic API to retrieve glucose data of the current installed device from the user you followed (This requires you to have a follow relationship with the other user which you want to monitor the glucose data)
2. It caches the glucose data into a file, and will only process new datas not showing in the cache
3. It also compares the most recent record from nightscout service, only data after the most recent recorded will be processed
4. Thos new glucose data will then be uploaded to the nightscout service
