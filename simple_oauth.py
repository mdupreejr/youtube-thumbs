#!/usr/bin/env python3
"""Simple OAuth setup using console flow"""

from google_auth_oauthlib.flow import InstalledAppFlow
import pickle

SCOPES = ['https://www.googleapis.com/auth/youtube']

print("Starting OAuth setup with console flow...")
print()

flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)

print("This will start a local web server and open your browser.")
print("If the browser doesn't open automatically, copy the URL from the output.")
print("After authorizing, the browser will redirect and the script will continue.")
print()

creds = flow.run_local_server(port=8080)

with open('token.pickle', 'wb') as f:
    pickle.dump(creds, f)

print()
print("✅ Success! token.pickle created")
print("You can now run: python app.py")
