
# Before running
1. Modify `config.py`, fill in all the values to access your web service provider's APIs

# Running
```
python process.py
```

# How it works
1. It reads the SiBionic API to retrieve glucose data of the current installed device from the user you followed (This requires you to have a follow relationship with the other user which you want to monitor the glucose data)
2. It caches the glucose data into a file, and will only process new datas not showing in the cache
3. Thos new glucose data will then be uploaded to the nightscout service
