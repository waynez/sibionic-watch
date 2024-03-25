
# Before running

1. Modify `config.py`, fill in all the values to access your web service provider's APIs

# Running
```
python process.py
```

Run with a dedicated directory for cache saving
```
python process.py --cache_dir=/path/to/cache/dir/
```

## Using docker

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
